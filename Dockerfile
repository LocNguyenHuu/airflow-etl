FROM tensorflow/tensorflow:1.13.2-gpu-py3



ARG BUILD_DATE
ARG VERSION
ARG SONIA_USER=sonia
ARG SONIA_UID=50000
ARG BASE_LIB_NAME=apache-airflow

ARG DOCKER_GROUP_ID=999
ARG BUILD_ENV="local"

ARG PROTOC_VERSION=3.10.1
ARG PROTOC_ZIP=protoc-${PROTOC_VERSION}-linux-x86_64.zip
ARG TENSORFLOW_OBJ_DETECTION_VERSION=1.13.0
ARG TENSORFLOW_OBJECT_DETECTION_LIB_PATH=${AIRFLOW_HOME}/models-${TENSORFLOW_OBJ_DETECTION_VERSION}/research/
ARG TENSORFLOW_OBJECT_DETECTION_SLIM_PATH=${AIRFLOW_HOME}/models-${TENSORFLOW_OBJ_DETECTION_VERSION}/research/slim

LABEL maintainer="club.sonia@etsmtl.net"
LABEL description="A docker image of Airflow an ETL orchestration plateform with GPU Support"
LABEL net.etsmtl.sonia-auv.base_lib.build-date=${BUILD_DATE}
LABEL net.etsmtl.sonia-auv.base_lib.version=${VERSION}
LABEL net.etsmtl.sonia-auv.base_lib.name=${BASE_LIB_NAME}

# Make sure noninteractive debian install is used and language variables set
ENV DEBIAN_FRONTEND=noninteractive \
    LANGUAGE=C.UTF-8 LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    LC_CTYPE=C.UTF-8 LC_MESSAGES=C.UTF-8

# Airflow
ENV AIRFLOW_HOME=/usr/local/airflow

# Tensorflow Object Detection API
ENV PROTOC_VERSION=${PROTOC_VERSION}
ENV TENSORFLOW_OBJECT_DETECTION_VERSION=${TENSORFLOW_OBJ_DETECTION_VERSION}

RUN set -ex \
    && buildDeps=' \
    freetds-dev \
    libkrb5-dev \
    libsasl2-dev \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    git \
    unzip \
    wget \
    lsb-release \
    gnupg2 \
    software-properties-common \
    ' \
    && apt-get update -yqq \
    && apt-get upgrade -yqq \
    && apt-get install -yqq --no-install-recommends \
    $buildDeps \
    freetds-bin \
    build-essential \
    default-libmysqlclient-dev \
    apt-utils \
    curl \
    rsync \
    netcat \
    locales \
    ca-certificates \
    apt-transport-https \
    libglib2.0-0 \
    libsm6 \
    libfontconfig1 \
    libxrender1 \
    libxext6 \
    && sed -i 's/^# en_US.UTF-8 UTF-8$/en_US.UTF-8 UTF-8/g' /etc/locale.gen \
    && locale-gen \
    && update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 \
    && addgroup --gid ${DOCKER_GROUP_ID} docker \
    && useradd -ms /bin/bash -d ${AIRFLOW_HOME} -G docker airflow \
    && pip install -U pip setuptools wheel \
    && apt-get purge --auto-remove -yqq $buildDeps \
    && apt-get autoremove -yqq --purge \
    && apt-get clean \
    && rm -rf \
    /var/lib/apt/lists/* \
    /tmp/* \
    /var/tmp/* \
    /usr/share/man \
    /usr/share/doc \
    /usr/share/doc-base

# Installing Airflow and other pythons requirements
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Installing protobuf (Binary serialization) required for tfrecord creation
# Intalling tensorflow object detection framework
RUN set -ex \
    && buildDeps=' \
    unzip \
    wget \
    ' \
    && apt-get update -yqq \
    && apt-get upgrade -yqq \
    && apt-get install -yqq --no-install-recommends \
    $buildDeps \
    && curl -OL https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/${PROTOC_ZIP} \
    && unzip -o ${PROTOC_ZIP} -d /usr/local bin/protoc \
    && unzip -o ${PROTOC_ZIP} -d /usr/local 'include/*' \
    && rm -f ${PROTOC_ZIP}\
    && wget -q -c https://github.com/tensorflow/models/archive/v${TENSORFLOW_OBJECT_DETECTION_VERSION}.tar.gz -O - | tar -xz -C ${AIRFLOW_HOME} \
    && cd ${AIRFLOW_HOME}/models-${TENSORFLOW_OBJECT_DETECTION_VERSION}/research/ \
    && protoc object_detection/protos/*.proto --python_out=. \
    && apt-get purge --auto-remove -yqq $buildDeps\
    && apt-get purge --auto-remove -yqq $buildDeps\
    && rm -rf \
    /var/lib/apt/lists/* \
    /tmp/* \
    /var/tmp/* \
    /usr/share/man \
    /usr/share/doc \
    /usr/share/doc-base

ENV PYTHONPATH=${PYTHONPATH}:${TENSORFLOW_OBJECT_DETECTION_LIB_PATH}:${TENSORFLOW_OBJECT_DETECTION_SLIM_PATH}

# *********************************************
# Creating airflow logs folder
RUN mkdir -p ${AIRFLOW_HOME}/logs
RUN mkdir -p ${AIRFLOW_HOME}/.config/gcloud/

# *********************************************
#Copying our airflow config and setting ownership
COPY config/airflow.cfg ${AIRFLOW_HOME}/airflow.cfg
COPY config/variables.json ${AIRFLOW_HOME}/variables.json
RUN chown -R airflow: ${AIRFLOW_HOME}

# Copying our docker entrypoint
COPY scripts/entrypoint.sh /entrypoint.sh

EXPOSE 8080

USER airflow
WORKDIR ${AIRFLOW_HOME}
ENTRYPOINT ["/entrypoint.sh"]
