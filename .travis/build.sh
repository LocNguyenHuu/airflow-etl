#!/usr/bin/env bash

echo ${TRAVIS_BRANCH}

if [ ${TRAVIS_BRANCH} == 'master' ]; then

elif [ ${TRAVIS_BRANCH} =~ ^/^release/\w-\d-\d-\d]; then


elif [${TRAVIS_BRANCH} == 'develop']; then

else
