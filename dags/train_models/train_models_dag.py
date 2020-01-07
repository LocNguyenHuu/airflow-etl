import os
import json
from datetime import datetime
from glob import glob

from airflow import DAG
from airflow.hooks.base_hook import BaseHook
from airflow.models import Variable
from airflow.operators.bash_operator import BashOperator
from airflow.operators.dummy_operator import DummyOperator
from airflow.operators.python_operator import PythonOperator

from train_models import train_models
from utils import file_ops, slack

AIRFLOW_BASE_FOLDER = "/usr/local/airflow/"
AIRFLOW_DATA_FOLDER = os.path.join(AIRFLOW_BASE_FOLDER, "data")
AIRFLOW_TRAINABLE_FOLDER = os.path.join(AIRFLOW_DATA_FOLDER, "trainable")

TENSORFLOW_OBJECT_DETECTION_RESEARCH_FOLDER = os.environ[
    "TENSORFLOW_OBJECT_DETECTION_RESEARCH_FOLDER"
]

GCP_ZONE = Variable.get("gcp_zone")

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2019, 1, 24),
    "email": ["club.sonia@etsmtl.net"],
    "email_on_failure": False,
    "email_on_retry": False,
    "on_failure_callback": slack.task_fail_slack_alert,
    "retries": 0,
}


dag = DAG("train_model", default_args=default_args, catchup=False, schedule_interval=None)

start_task = DummyOperator(task_id="start_task", dag=dag)
end_task = DummyOperator(task_id="end_task", dag=dag)


package_tensorflow_libs_cmd = f"cd {TENSORFLOW_OBJECT_DETECTION_RESEARCH_FOLDER} && object_detection/dataset_tools/create_pycocotools_package.sh /tmp/pycocotools && python setup.py sdist && (cd slim && python setup.py sdist)"

package_tensorflow_libs_with_dependencies = BashOperator(
    task_id="package_tensorflow_libs_with_dependencies",
    bash_command=package_tensorflow_libs_cmd,
    dag=dag,
)

training_tasks = []

for json_file in glob(f"{AIRFLOW_TRAINABLE_FOLDER}/*.json"):

    training_name = file_ops.get_filename(json_file, with_extension=False)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    training_name_with_date = f"{training_name}_{now}"
    gcp_url = train_models.get_gcp_training_data_url(json_file)

    cd_obj_detect_api_cmd = f"cd {TENSORFLOW_OBJECT_DETECTION_RESEARCH_FOLDER}"
    job_dir = gcp_url + "/"
    packages = "dist/object_detection-0.1.tar.gz,slim/dist/slim-0.1.tar.gz,/tmp/pycocotools/pycocotools-2.0.tar.gz"
    module_name = "object_detection.model_main"
    runtime_version = "1.13"
    scale_tier = "BASIC_GPU"
    region = GCP_ZONE
    model_dir = gcp_url + "/train_data/"
    pipeline_config_path = f"{gcp_url}/pipeline.config"
    checkpoint_dir = model_dir

    train_model_on_basic_gpu_cmd = f"{cd_obj_detect_api_cmd} && gcloud ai-platform jobs submit training train_{training_name}_`date +%s` --job-dir={job_dir} --packages {packages} --module-name {module_name} --runtime-version {runtime_version} --scale-tier {scale_tier} --region {region} -- --model_dir={model_dir} --pipeline_config_path={pipeline_config_path}"

    train_model_on_basic_gpu = BashOperator(
        task_id="train_model_" + training_name + "_on_basic_gpu",
        bash_command=train_model_on_basic_gpu_cmd,
        dag=dag,
    )

    delay_eval_task = BashOperator(
        task_id="delay_eval_" + training_name, bash_command="sleep 6m", dag=dag
    )

    eval_model_on_basic_gpu_cmd = f"{cd_obj_detect_api_cmd} && gcloud ai-platform jobs submit training eval_{training_name}_`date +%s` --job-dir={job_dir} --packages {packages} --module-name {module_name} --runtime-version {runtime_version} --scale-tier {scale_tier} --region {region} -- --model_dir={model_dir} --pipeline_config_path={pipeline_config_path} --checkpoint_dir={checkpoint_dir}"

    eval_model_on_basic_gpu = BashOperator(
        task_id="eval_model_" + training_name + "_on_basic_gpu",
        bash_command=eval_model_on_basic_gpu_cmd,
        dag=dag,
    )

    start_task >> package_tensorflow_libs_with_dependencies
    package_tensorflow_libs_with_dependencies >> train_model_on_basic_gpu >> delay_eval_task >> eval_model_on_basic_gpu >> end_task

# TODO: Handle tpu training
# TODO: Handle parallel gpu training
