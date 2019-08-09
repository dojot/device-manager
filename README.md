# DeviceManager

[![License badge](https://img.shields.io/badge/license-GPL-blue.svg)](https://opensource.org/licenses/GPL-3.0)
[![Docker badge](https://img.shields.io/docker/pulls/dojot/iotagent-json.svg)](https://hub.docker.com/r/dojot/device-manager/)

The DeviceManager handles all operations related to creation, retrieval, update and deletion of devices in dojot. For more information
on that, check [Device Manager Concepts page](./docs/concepts.rst).

**Before running all those steps a Kafka and a Postgres database must be running**

## How does it work

DeviceManager stores and retrieves information models for devices and templates and a few static information about them as well. Whenever a device is created, removed or just edited, it will publish a message through Kafka. It depends only on DataBroker and Kafka.
All messages published by Device Manager to Kafka can be seen in [Device Manager Messages](https://dojotdocs.readthedocs.io/projects/DeviceManager/en/latest/kafka-messages.html).

## Dependencies

DeviceManager has the following dependencies:

- flask (including flask_sqlalchemy, flask_migrate and flask_alembic)
- psycopg2
- marshmallow
- requests
- gunicorn
- gevent
- json-logging-py
- kakfa-python
- redis

But you won't need to worry about installing any of these - they are automatically installed when starting DeviceManager.

## Configuration

These are the environment variables used by device-manager

Key                     | Purpose                                                       | Default Value
----------------------- | --------------------------------------------------------------| --------------
DBNAME                  | postgres database name                                        | dojot_devm
DBHOST                  | postgres database host                                        | postgres
DBUSER                  | postgres database user                                        | postgres
DBPASS                  | postgres database password                                    | none
DBDRIVER                | postgres database driver                                      | postgresql+psycopg2
CREATE_DB               | option to create the database                                 | True
KAFKA_HOST              | kafka host                                                    | kafka
KAFKA_PORT              | kafka port                                                    | 9092
STATUS_TIMEOUT          | kafka timeout                                                 | 5
BROKER                  | kafka topic subject manager                                   | http://data-broker
REDIS_HOST              | redis host                                                    | device-manager-redis
REDIS_PORT              | redis port                                                    | 6379
DEV_MNGR_CRYPTO_PASS    | password of crypto                                            | none
DEV_MNGR_CRYPTO_IV      | inicialization vector of crypto                               | none
DEV_MNGR_CRYPTO_SALT    | salt of crypto                                                | none
LOG_LEVEL               | logger level (DEBUG, ERROR, WARNING, CRITICAL, INFO, NOTSET)  | INFO

## Internal Messages

There are some messages that are published by DeviceManager through Kafka. These messages are notifications of device management operations, and they can be consumed by any component interested in them, such as IoT agents.

Event                   | Service                                             | Message Type
----------------------- | --------------------------------------------------- | --------------
Device creation         | dojot.device-manager.device                         | Creation message
Device update           | dojot.device-manager.device                         | Update message
Device removal          | dojot.device-manager.device                         | Removal message
Device actuation        | dojot.device-manager.device                         | Actuation message
Template update         | dojot.device-manager.device                         | Template update message

## How to run

A docker image is available on dockerhub for pull [here](https://hub.docker.com/r/dojot/device-manager)

If you really need to run DeviceManager as a standalone process (without dojot's wonderful [docker-compose](https://github.com/dojot/docker-compose), we suggest using the minimal compose
file available under `local/compose.yml`. That contains only the set of external systems (postgres
and kafka) that are used by device manager to implement its features. To have this minimal environment
running, please:

```shell
# spin up local copies of remote dependencies
docker-compose -f local/compose.yml -p devm up -d
# Builds devm container (this may take a while)
docker build -f Dockerfile -t local/devicemanager .
# Runs devm manually, using the infra that's been just created
# Must pass the environment variables of cryto to run
docker run --rm -it --network devm_default -e DEV_MNGR_CRYPTO_PASS=${CRYPTO_PASS} -e DEV_MNGR_CRYPTO_IV=${CRYPTO_IV} -e DEV_MNGR_CRYPTO_SALT=${CRYPTO_SALT} local/devicemanager
# 
# Example: docker run --rm -it --network devm_default -e DEV_MNGR_CRYPTO_PASS='kamehameHA'  -e DEV_MNGR_CRYPTO_IV=1234567890123456 -e DEV_MNGR_CRYPTO_SALT='shuriken' local/devicemanager
#
# Hitting ^C will actually kill device-manager's process and the container
#
```

"Ok, but I ***really*** want to run device manager on my machine - no docker no nothing."

 You can execute the following commands (it's just what runs in the container, actually - check
 `docker/entrypoint.sh` and `Dockerfile`).

```shell
# install dependencies locally (may take a while)
python setup.py develop

export DBHOST="postgres ip/hostname goes here"
export KAFKA_HOST="kafka ip/hostname goes here"

docker/waitForDb.py
gunicorn DeviceManager.main:app -k gevent --logfile - --access-logfile -
```

Do notice that all those external infra (kafka and postgres) will have to be up and running still.
At a minimum, please remember to configure the two environment variables above, to their real values
(specially if they are both `localhost`).

Keep in mind that running a standalone instance of DeviceManager misses a lot of security checks
(such as user identity checks, proper multi-tenancy validations, and so on). In particular,
every request sent to DeviceManager needs an access token, which should be retrived from
[auth](https://github.com/dojot/auth) component. In the examples listed in this README, you
can generate one by yourself (for now, DeviceManager doesn't check if the token is actually
valid for that user - they are verified by auth and the API gateway) but this method might not
work in the future as more strict token checks are implemented in DeviceManager.

## How to use

There are a few examples on how to use DeviceManager in [Device Manager Documentation](https://dojotdocs.readthedocs.io/projects/DeviceManager/en/latest/using-device-manager.html).

## API Documentation

URL to api documentation for [development](https://dojot.github.io/device-manager/apiary_development.html) and [latest version](https://dojot.github.io/device-manager/apiary_latest.html) of this Device Manager.