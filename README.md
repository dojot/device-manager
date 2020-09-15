# Device Manager

[![License badge](https://img.shields.io/badge/license-GPL-blue.svg)](https://opensource.org/licenses/GPL-3.0)
[![Docker badge](https://img.shields.io/docker/pulls/dojot/iotagent-json.svg)](https://hub.docker.com/r/dojot/device-manager/)

The Device Manager handles all CRUD operations related to devices in dojot. For more information on
that, check [Device Manager Concepts page](./docs/concepts.rst).

## How does it work

The Device Manager stores and retrieves information models for devices and templates and a few
static information about them as well. Whenever a device is created, removed or just edited, it will
publish a message through Kafka. All messages published by the Device Manager to Kafka can be seen
in [Device Manager Messages](https://dojotdocs.readthedocs.io/projects/DeviceManager/en/latest/kafka-messages.html).

## Dependencies

### Dojot services

The minimal set of dojot services needed to run Device Manager is:

- Kafka
- Data Broker
- PostgreSQL

### Python libraries

Check the [requirements file](./requirements/requirements.txt) for more details.

## Configuration

Key                  | Purpose                         | Default Value       | Accepted values
-------------------- | ------------------------------- | ------------------- | -------------------------------------
BROKER               | Kafka topic subject manager     | http://data-broker  | Hostname
CREATE_DB            | Option to create the database   | True                | Boolean
DBDRIVER             | PostgreSQL database driver      | postgresql+psycopg2 | String
DBHOST               | PostgreSQL database host        | postgres            | String
DBNAME               | PostgreSQL database name        | dojot_devm          | String
DBPASS               | PostgreSQL database password    | none                | String
DBUSER               | PostgreSQL database user        | postgres            | String
DEV_MNGR_CRYPTO_IV   | Inicialization vector of crypto | none                | String
DEV_MNGR_CRYPTO_PASS | Password of crypto              | none                | String
DEV_MNGR_CRYPTO_SALT | Salt of crypto                  | none                | String
KAFKA_HOST           | Kafka host                      | kafka               | Hostname
KAFKA_PORT           | Kafka port                      | 9092                | Number
LOG_LEVEL            | Logger level                    | INFO                | DEBUG, ERROR, WARNING, CRITICAL, INFO
STATUS_TIMEOUT       | Kafka timeout                   | 5                   | Number

## Internal Messages

There are some messages that are published by Device Manager to Kafka. These messages are
notifications of device management operations, and they can be consumed by any component interested
in them, such as IoT agents.

Event            | Service                     | Message Type
---------------- | --------------------------- | -----------------------
Device creation  | dojot.device-manager.device | Creation message
Device update    | dojot.device-manager.device | Update message
Device removal   | dojot.device-manager.device | Removal message
Device actuation | dojot.device-manager.device | Actuation message
Template update  | dojot.device-manager.device | Template update message

## How to run

For a simple and fast setup, an official Docker image for this service is available on
[DockerHub](https://hub.docker.com/r/dojot/device-manager).

### Standalone - with Docker

If you really need to run Device Manager as a standalone process (without dojot's wonderful
[Docker Compose](https://github.com/dojot/docker-compose), we suggest using the minimal
[Docker Compose file](local/compose.yml). It contains only the minimum set of external services. To
run them, follow these instructions:

```shell
# Spin up local copies of remote dependencies
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

### Standalone - without Docker

"Ok, but I ***really*** want to run device manager on my machine - no Docker no nothing."

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

Do notice that all those external infra (Kafka and PostgreSQL) will have to be up and running still.
At a minimum, please remember to configure the two environment variables above (specially if they
are both `localhost`).

Keep in mind that running a standalone instance of DeviceManager misses a lot of security checks
(such as user identity checks, proper multi-tenancy validations, and so on). In particular, every
request sent to DeviceManager needs an access token, which should be retrived from the
[Auth](https://github.com/dojot/auth) component. In the examples listed in this README, you can
generate one by yourself (for now, Device Manager doesn't check if the token is actually valid for
that user - they are verified by Auth and the API gateway), but this method might not work in the
future as more strict token checks are implemented in this service.

## Documentation

If you have any doubts, check the documentation for more details.

- API
  - [Development](https://dojot.github.io/device-manager/apiary_development.html)
  - [Latest](https://dojot.github.io/device-manager/apiary_latest.html)
- [Read the docs](https://dojotdocs.readthedocs.io/projects/DeviceManager/en/latest/)
  - [How to use](https://dojotdocs.readthedocs.io/projects/DeviceManager/en/latest/using-device-manager.html)
