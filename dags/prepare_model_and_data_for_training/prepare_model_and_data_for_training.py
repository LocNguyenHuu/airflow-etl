import filecmp
import glob
import json
import logging
import os
import re
import shutil
import tarfile

import pandas as pd
import requests

import mistune
from bs4 import BeautifulSoup
from utils import file_ops

logging.getLogger().setLevel(logging.INFO)


def __parse_downloaded_model_file_list_response(response):
    """__parse_downloaded_model_file_list_response

    Utility function which parse model csv file and download
    model from tensorflow model zoo

    :param response: A request response
    :type response: request.Response
    :return: A dataframe that contains model release information
    :rtype: pandas.Dataframe
    """
    html = mistune.markdown(response.text)
    soup = BeautifulSoup(html)
    link_nodes = soup.find_all("a")

    data = []
    for link in link_nodes:
        if "http://download.tensorflow.org/models/object_detection/" in link.attrs["href"]:
            model_name = link.text
            model_name = model_name.replace("☆", "")
            model_name = model_name.strip()

            model_url = link.attrs["href"]
            model_file_name = model_url.split("/")[-1]
            model_folder_name = os.path.splitext(os.path.basename(model_file_name))[0]
            model_folder_name = os.path.splitext(os.path.basename(model_folder_name))[0]
            try:
                model_release_date = re.search(r"\d{4}_\d{2}_\d{2}", model_file_name).group()
            except:
                model_release_date = None

            data.append(
                (model_release_date, model_folder_name, model_file_name, model_url, model_name)
            )

    logging.info(f"Parsed all model data from the webpage {response.url}")

    return pd.DataFrame(
        data,
        columns=[
            "model_release_date",
            "model_folder_name",
            "model_file_name",
            "model_url",
            "model_name",
        ],
    )


def validate_reference_model_list_exist_or_create(
    base_model_csv, positive_downstream, negative_downstream
):
    """validate_reference_model_list_exist_or_create

    A simple function to handle airflow BranchyPythonOperator downstream

    :param base_model_csv: A CSV file which contains models informations
    :type base_model_csv: CSV file path
    :param positive_downstream: Positive Downstream task name
    :type positive_downstream: str
    :param negative_downstream: Negative Downstream task name
    :type negative_downstream: str
    :return: Downstream task name
    :rtype: str
    """

    if file_ops.file_exist(base_model_csv):
        return positive_downstream
    else:
        return negative_downstream


def download_reference_model_list_as_csv(url, base_model_csv):
    """download_reference_model_list_as_csv

    A utility function to download all the requested model
    from tensorflow model zoo

    :param url: Url of the model list
    :type url: str
    :param base_model_csv: CSV file path
    :type base_model_csv: str
    """
    try:
        response = requests.get(url, allow_redirects=True)
        new_models_reference_df = __parse_downloaded_model_file_list_response(response)
        new_models_reference_df.to_csv(base_model_csv)
        logging.info("Model list data saved to csv file")
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while downloading the file from {url}")


def download_and_extract_base_model(base_model_csv, base_model_folder, required_base_models=None):
    """download_and_extract_base_model

     Utility function which handle model tar file download and extraction

    :param base_model_csv: CSV file path
    :type base_model_csv: str
    :param base_model_folder: Base model folder directory
    :type base_model_folder: str
    :param required_base_models: A list of required base model, defaults to None
    :type required_base_models: list, optional
    """

    models_df = pd.read_csv(base_model_csv)
    models_subset = models_df[["model_folder_name", "model_file_name", "model_url", "model_name"]]

    if required_base_models is not None:
        models_subset = models_subset[models_df.model_name.isin(required_base_models)]

    models = [tuple(x) for x in models_subset.values]
    subfolders = file_ops.get_subfolders_names_in_directory(base_model_folder)

    for model_folder_name, model_file_name, model_url, model_name in models:
        if not model_folder_name in subfolders:
            logging.info(f"Model {model_folder_name} not found ")
            os.mkdir(os.path.join(base_model_folder, model_folder_name))
            try:
                response = requests.get(model_url, stream=True)
                logging.info(f"Downloading {model_url} .....")
                if response.status_code == 200:
                    tar_file = os.path.join(base_model_folder, model_file_name)
                    with open(tar_file, "wb") as f:
                        f.write(response.raw.read())

                    logging.info(f"Extracting {tar_file} .....")
                    shutil.unpack_archive(tar_file, os.path.join(base_model_folder))
                    os.remove(tar_file)
            except requests.exceptions.RequestException as e:
                logging.error(f"An error occurred while downloading the file from {model_url}")
        else:
            logging.info("All base models are already present")


def compare_label_map_file(base_tf_record_folder, video_source):
    """compare_label_map_file

    A utility funcction to compare content of base model csv file
    and current parsed content from tensorflow model zoo url

    :param base_tf_record_folder: TF record directory
    :type base_tf_record_folder: str
    :param video_source: Current video source
    :type video_source: str
    :return: Does match or not
    :rtype: Boolean
    """

    subfolders = file_ops.get_directory_subfolders_subset(base_tf_record_folder, video_source)

    if len(subfolders) > 1:
        label_maps = []
        for subfolder in subfolders:
            label_maps.append(glob.glob(subfolder + "*.pbtxt")[0])
        reference_label_map = label_maps[0]
        labelmap_match = True
        for label_map in label_maps:
            print(label_map)
            logging.info(f"Reference File: {reference_label_map}")
            if filecmp.cmp(label_map, reference_label_map):
                print(f"[ MATCH ] | LabelMap:{label_map} ")
            else:
                print(f"[ FAILED ] | LabelMap:{label_map} ")
                labelmap_match = False

        return labelmap_match
    else:
        logging.warn(f"There were not enough dataset to compare i.g : Less than two")


def validate_requested_model_exist_in_model_zoo_list(base_models_csv, required_base_models):
    """validate_requested_model_exist_in_model_zoo_list

    A utility function to validate if a requested model is currently
    available from tensorflow model zoo

    :param base_models_csv: Model CSV file path
    :type base_models_csv: str
    :param required_base_models: A list of required models
    :type required_base_models: list
    :raises ValueError: Required model list is empty error
    :raises ValueError: Required model does not exist in tensorflow model zoo list
    """

    df = pd.read_csv(base_models_csv)
    available_models = df["model_name"].unique()

    if len(required_base_models) <= 0:
        raise ValueError(
            "Airflow variable training_required_base_models should contain at least one model to train"
        )

    for required_model in required_base_models:
        if required_model not in available_models:
            raise ValueError(
                "Required model {required_model} does not exist in the official tensorflow model zoo"
            )
    logging.info("All required model exist in the official tensorflow model zoo reference list")


def validate_model_presence_in_model_repo_or_create(model_repo_folder):
    """validate_model_presence_in_model_repo_or_create

    A utility function to validate model repo exist otherwise create it

    :param model_repo_folder: Model repo folder path
    :type model_repo_folder: str
    """

    file_ops.folder_exist_or_create(model_repo_folder)

    logging.info("Model directory present in model repository")


def create_training_folder(model_training_folder):
    """
    create_training_folder

    A utility function to create training folder

    :param model_training_folder: Training folder directory
    :type model_training_folder: str
    """

    file_ops.folder_exist_or_create(model_training_folder)

    logging.info("Temporary training folder created")


def copy_images_to_output(labelbox_output_folder, output_folder, video_source):
    """copy_images_to_output

    A utility function to copy images from multiple labelbox output project
    to one training project

    :param labelbox_output_folder: Labelbox output directory
    :type labelbox_output_folder: str
    :param output_folder: Output directory
    :type output_folder: str
    :param video_source: Current video source
    :type video_source: str
    """
    filtered_subfolders = file_ops.get_directory_subfolders_subset(
        labelbox_output_folder, video_source
    )

    for subfolder in filtered_subfolders:
        subfolders = file_ops.get_subfolders_in_directory(subfolder)

        subfolders = [
            image_subfolder for image_subfolder in subfolders if image_subfolder.endswith("images")
        ]

        folder = subfolders[0]
        file_ops.copy_files_from_folder(folder, output_folder)


def copy_labelbox_output_images_to_training_folder(
    labelbox_output_folder, model_training_images_folder, video_source
):
    """copy_labelbox_output_images_to_training_folder

    A utility function to copy labelbox output images to training images folder

    :param labelbox_output_folder: Labelbox output directory
    :type labelbox_output_folder: str
    :param model_training_images_folder: Model training images directory
    :type model_training_images_folder: str
    :param video_source: Current video source
    :type video_source: str
    """
    file_ops.folder_exist_or_create(model_training_images_folder)

    copy_images_to_output(labelbox_output_folder, model_training_images_folder, video_source)

    logging.info("Images copied to temporary image folder")


def copy_labelbox_output_images_to_model_repo_folder(
    labelbox_output_folder, model_repo_images_folder, video_source
):
    """copy_labelbox_output_images_to_model_repo_folder

     A utility function to copy labelbox output images to model repo images folder

    :param labelbox_output_folder: Labelbox output directory
    :type labelbox_output_folder: str
    :param model_repo_images_folder: Model repo images directory
    :type model_repo_images_folder: str
    :param video_source: Current video source
    :type video_source: str
    """
    file_ops.folder_exist_or_create(model_repo_images_folder)

    copy_images_to_output(labelbox_output_folder, model_repo_images_folder, video_source)

    logging.info("Images copied to model repo image folder")


def copy_labelbox_output_annotations_to_model_repo_folder(
    labelbox_output_folder, model_repo_annotations_folder, video_source
):
    """copy_labelbox_output_annotations_to_model_repo_folder

    A utility function to copy annotations files to model repo

    :param labelbox_output_folder: Labelbox output directory
    :type labelbox_output_folder: str
    :param model_repo_annotations_folder: Model repo annotations folder
    :type model_repo_annotations_folder: str
    :param video_source: Current video source
    :type video_source: str
    """
    file_ops.folder_exist_or_create(model_repo_annotations_folder)

    copy_images_to_output(labelbox_output_folder, model_repo_annotations_folder, video_source)

    logging.info("Annotations copied to model repo annotations folder")


def copy_tf_records_to_training_folder(
    tf_records_folder, model_training_tf_records_folder, video_source,
):
    """copy_tf_records_to_training_folder

    A utility function to copy tf records to training folder

    :param tf_records_folder: TF record directory path
    :type tf_records_folder: str
    :param model_training_tf_records_folder: Model training tf record directory
    :type model_training_tf_records_folder: str
    :param video_source: Current Video Source
    :type video_source: str
    """
    training_tf_records_train_folder = f"{model_training_tf_records_folder}/train"
    training_tf_records_val_folder = f"{model_training_tf_records_folder}/val"

    file_ops.folder_exist_or_create(training_tf_records_train_folder)
    file_ops.folder_exist_or_create(training_tf_records_val_folder)

    subfolders = file_ops.get_directory_subfolders_subset(tf_records_folder, video_source)

    labelmap_files = []
    tf_record_train_files = []
    tf_record_val_files = []
    for subfolder in subfolders:
        labelmap_files.extend(glob.glob(subfolder + "/*.pbtxt"))
        tf_record_train_files.extend(glob.glob(subfolder + "/*_train.record"))
        tf_record_val_files.extend(glob.glob(subfolder + "/*_val.record"))

    for tf_record in tf_record_train_files:
        shutil.copy2(tf_record, training_tf_records_train_folder)
        logging.info(f"Copied {tf_record} to {training_tf_records_train_folder}")

    for tf_record in tf_record_val_files:
        shutil.copy2(tf_record, training_tf_records_val_folder)
        logging.info(f"Copied {tf_record} to {training_tf_records_val_folder}")

    labelmap_file = f"{model_training_tf_records_folder}/labelmap.pbtxt"
    with open(labelmap_file, "w") as outfile:
        with open(labelmap_files[0]) as infile:
            for line in infile:
                outfile.write(line)
        logging.info(f"Copied {labelmap_file} to {model_training_tf_records_folder}")

    logging.info("Completed copy of all tf records file to temporary training tf records folder")


def copy_tf_records_to_model_repo(tf_records_folder, model_repo_tf_records_folder, video_source):
    """copy_tf_records_to_model_repo

    A utility function to copy tf records to training folder

    :param tf_records_folder: TF record directory path
    :type tf_records_folder: str
    :param model_repo_tf_records_folder: Model repo tf record directory path
    :type model_repo_tf_records_folder: str
    :param video_source: Current video source
    :type video_source: str
    """
    model_repo_tf_record_train_folder = f"{model_repo_tf_records_folder}/train"
    model_repo_tf_records_val_folder = f"{model_repo_tf_records_folder}/val"

    file_ops.folder_exist_or_create(model_repo_tf_record_train_folder)
    file_ops.folder_exist_or_create(model_repo_tf_records_val_folder)

    subfolders = file_ops.get_directory_subfolders_subset(tf_records_folder, video_source)

    labelmap_files = []
    trainval_files = []
    tf_record_train_files = []
    tf_record_val_files = []
    for subfolder in subfolders:
        labelmap_files.extend(glob.glob(subfolder + "/*.pbtxt"))
        trainval_files.extend(glob.glob(subfolder + "/*.txt"))
        tf_record_train_files.extend(glob.glob(subfolder + "/*_train.record"))
        tf_record_val_files.extend(glob.glob(subfolder + "/*_val.record"))

    for tf_record in tf_record_train_files:
        shutil.copy2(tf_record, model_repo_tf_record_train_folder)
        logging.info(f"Copied {tf_record} to {model_repo_tf_record_train_folder}")

    for tf_record in tf_record_val_files:
        shutil.copy2(tf_record, model_repo_tf_records_val_folder)
        logging.info(f"Copied {tf_record} to {model_repo_tf_records_val_folder}")

    labelmap_file = f"{model_repo_tf_records_folder}/labelmap.pbtxt"
    with open(labelmap_file, "w") as outfile:
        with open(labelmap_files[0]) as infile:
            for line in infile:
                outfile.write(line)
        logging.info(f"Copied {labelmap_file} to {model_repo_tf_records_folder}")

    trainval_file = f"{model_repo_tf_records_folder}/trainval.txt"
    with open(trainval_file, "w") as outfile:
        for trainval_file in trainval_files:
            with open(trainval_file, "r") as infile:
                shutil.copyfileobj(infile, outfile)
        logging.info(f"trainval file created in {model_repo_tf_records_folder}")

    logging.info("Completed copy of all tf records file to temporary training tf records folder")


def copy_base_model_to_training_folder(
    base_model, base_model_csv, base_model_folder, model_training_base_model_folder
):
    """copy_base_model_to_training_folder

    A utility function to copy base model to training folder

    :param base_model: Base model name
    :type base_model: str
    :param base_model_csv: Base model CSV file path
    :type base_model_csv: str
    :param base_model_folder: Base model download directory
    :type base_model_folder: str
    :param model_training_base_model_folder: Base model training directory
    :type model_training_base_model_folder: str
    """
    base_models_df = pd.read_csv(base_model_csv)

    model_df = base_models_df.loc[base_models_df["model_name"] == base_model]

    base_model_folder_name = model_df.iloc[0]["model_folder_name"]

    model_folder = os.path.join(base_model_folder, base_model_folder_name)

    file_ops.folder_exist_or_create(model_training_base_model_folder)

    file_ops.copy_files_from_folder(model_folder, model_training_base_model_folder)

    pipeline_file = os.path.join(model_training_base_model_folder, "pipeline.config")

    os.remove(pipeline_file)

    logging.info(
        f"Base model {base_model} has been copied to temporary training folder {model_training_base_model_folder}"
    )


def copy_base_model_to_model_repo_folder(
    base_model, base_model_csv, base_model_folder, model_repo_base_model_folder
):
    """copy_base_model_to_model_repo_folder

    A utility function to copy base model to model repo model directory

    :param base_model: Base model name
    :type base_model: str
    :param base_model_csv: Base model CSV file path
    :type base_model_csv: str
    :param base_model_folder: Base model download directory
    :type base_model_folder: str
    :param model_repo_base_model_folder: Model repo base model directory
    :type model_repo_base_model_folder: str
    """
    base_models_df = pd.read_csv(base_model_csv)

    model_df = base_models_df.loc[base_models_df["model_name"] == base_model]

    base_model_folder_name = model_df.iloc[0]["model_folder_name"]

    model_folder = os.path.join(base_model_folder, base_model_folder_name)

    file_ops.folder_exist_or_create(model_repo_base_model_folder)

    file_ops.copy_files_from_folder(model_folder, model_repo_base_model_folder)

    pipeline_file = os.path.join(model_repo_base_model_folder, "pipeline.config")

    os.remove(pipeline_file)

    logging.info(
        f"Base model {base_model} has been copied to model repo folder {model_repo_base_model_folder}"
    )


def generate_model_config(
    model_training_folder,
    model_repo_folder,
    model_folder_ts,
    model_config_template,
    num_classes,
    bucket_url,
    training_batch_size,
    training_epoch_count,
):
    """generate_model_config

    A utility function to fill in value of the template model config file
    saved into airflow variables


    :param model_training_folder: Model training folder directory
    :type model_training_folder: str
    :param model_repo_folder: Model repo directory
    :type model_repo_folder: str
    :param model_folder_ts: Model folder name with timestamp
    :type model_folder_ts: str
    :param model_config_template: Model config template
    :type model_config_template: str
    :param num_classes: Number of class in the current model
    :type num_classes: str
    :param bucket_url: GCP bucket url
    :type bucket_url: str
    :param training_batch_size: Training batch size
    :type training_batch_size: str
    :param training_epoch_count: Training epoch count
    :type training_epoch_count: str
    :raises error: IOError on writing file on disk
    """

    pre_trained_model_checkpoint_path = f"{bucket_url}/{model_folder_ts}/model/base/model.ckpt"
    label_map_path = f"{bucket_url}/{model_folder_ts}/data/tf_records/labelmap.pbtxt"
    train_tf_record_path = f"{bucket_url}/{model_folder_ts}/data/tf_records/train/*.record"
    val_tf_record_path = f"{bucket_url}/{model_folder_ts}/data/tf_records/val/*.record"

    pipeline_config_files = [
        f"{model_training_folder}/pipeline.config",
        f"{model_repo_folder}/pipeline.config",
    ]

    model_config_template = re.sub("NUM_CLASSES", str(num_classes), model_config_template)
    model_config_template = re.sub(
        "PRE_TRAINED_MODEL_CHECKPOINT_PATH",
        pre_trained_model_checkpoint_path,
        model_config_template,
    )
    model_config_template = re.sub("LABEL_MAP_PATH", label_map_path, model_config_template)
    model_config_template = re.sub(
        "TRAIN_TF_RECORD_PATH", train_tf_record_path, model_config_template
    )
    model_config_template = re.sub("VAL_TF_RECORD_PATH", val_tf_record_path, model_config_template)
    model_config_template = re.sub(
        "TRAINING_BATCH_SIZE", str(training_batch_size), model_config_template
    )
    model_config_template = re.sub(
        "TRAINING_EPOCH_COUNT", str(training_epoch_count), model_config_template
    )

    for config_file in pipeline_config_files:
        try:
            with open(config_file, "w") as outfile:
                outfile.write(model_config_template)
            logging.info(f"Model config file has been created successfully at {config_file}")
        except IOError as error:
            logging.error(
                "An error has been raised while trying to save the model config to a file on disk"
            )
            raise e

    logging.info("Generated training pipeline config file")
