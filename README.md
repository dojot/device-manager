# Device Manager

[![License badge](https://img.shields.io/badge/license-GPL-blue.svg)](https://opensource.org/licenses/GPL-3.0)
[![Docker badge](https://img.shields.io/docker/pulls/dojot/iotagent-json.svg)](https://hub.docker.com/r/dojot/device-manager/)

The Device Manager handles all CRUD operations related to devices in dojot.

## How does it work

The Device Manager stores and retrieves information models for devices and templates and a few
static information about them as well. Whenever a device is created, removed or just edited, it will
publish a message through Kafka.

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
DEV_MNGR_CRYPTO_IV   | Initialization vector of crypto | none                | String
DEV_MNGR_CRYPTO_PASS | Password of crypto              | none                | String
DEV_MNGR_CRYPTO_SALT | Salt of crypto                  | none                | String
KAFKA_HOST           | Kafka host                      | kafka               | Hostname
KAFKA_PORT           | Kafka port                      | 9092                | Number
LOG_LEVEL            | Logger level                    | INFO                | DEBUG, ERROR, WARNING, CRITICAL, INFO
STATUS_TIMEOUT       | Kafka timeout                   | 5                   | Number

## How to run

For a simple and fast setup, an official Docker image for this service is available on
[DockerHub](https://hub.docker.com/r/dojot/device-manager).

### **Standalone - with Docker**

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

### **Standalone - without Docker**

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

Keep in mind that running a standalone instance of Device Manager misses a lot of security checks
(such as user identity checks, proper multi-tenancy validations, and so on). In particular, every
request sent to Device Manager needs an access token, which should be retrieved from the
[Auth](https://github.com/dojot/auth) component. In the examples listed in this README, you can
generate one by yourself (for now, Device Manager doesn't check if the token is actually valid for
that user - they are verified by Auth and the API gateway), but this method might not work in the
future as more strict token checks are implemented in this service.

## How to use

The usage is via the REST API. Check the
[API documentation](https://dojot.github.io/device-manager/apiary_latest.html) for more details.

## Concepts

This service holds two of the most basic and essential concepts in the dojot platform: the `device`
and the `template`. Before reading about the events, it's important to understand what each one is
and know their parameters.

### **Device**

In dojot, a device is a digital representation of an actual device or gateway with one or more
sensors or of a virtual one with sensors/attributes inferred from other devices.

Consider, for instance, an actual device with temperature and humidity sensors; it can be
represented into dojot as a device with two attributes (one for each sensor). We call this kind of
device as regular device or by its communication protocol, for instance, MQTT device or CoAP device.

We can also create devices which don’t directly correspond to their associated physical ones, for
instance, we can create one with higher level of information of temperature (is becoming hotter or
is becoming colder) whose values are inferred from temperature sensors of other devices. This kind
of device is called virtual device.

The information model used for both “real” and virtual devices is as following:

| Attribute     | Type                                                    | Mode       | Required | Description
| ------------- | ------------------------------------------------------- | ---------- | -------- | -------------------------------------------------------------------
| **attrs**     | Map of attributes                                       | read-only  | No       | Map of device's attributes (check the attributes in the next table)
| **created**   | DateTime (with timezone and µs precision) in ISO format | read-only  | No       | Device creation time.
| **id**        | String (length of 8 bytes)                              | read-only  | No       | Unique identifier for the device.
| **label**     | String (length of 128 bytes)                            | read-write | Yes      | An user-defined label to facilitate the device's identification.
| **templates** | Strings list                                            | read-only  | No       | List of template IDs used by the device.
| **updated**   | DateTime (with timezone and µs precision) in ISO format | read-only  | No       | Device last update time.

Example device:

```json
{
  "attrs": {
    "1": [
      {
        "created": "2020-09-16T14:50:09.297163+00:00",
        "id": 1,
        "is_static_overridden": false,
        "label": "rain",
        "static_value": "",
        "template_id": "1",
        "type": "dynamic",
        "value_type": "float"
      }
    ]
  },
  "created": "2020-09-16T14:50:34.749230+00:00",
  "updated": "2020-09-16T14:55:41.897400+00:00",
  "id": "e06357",
  "label": "teste",
  "templates": [
    1
  ]
}
```

The accepted parameters in the `attrs` map are:

| Attribute                | Type                                                    | Mode       | Required | Description
| ------------------------ | ------------------------------------------------------- | ---------- | -------- | -------------------------------------------------------------------
| **created**              | DateTime (with timezone and µs precision) in ISO format | read-only  | No       | Device creation time.
| **id**                   | Integer                                                 | read-write | No       | Unique identifier for the attribute (automatically generated).
| **is_static_overridden** | Bool                                                    | read-write | No       | Whether the static value were overridden.
| **label**                | String (length of 128 bytes)                            | read-write | Yes      | An user-defined label to facilitate the attribute's identification.
| **static_value**         | String (length of 128 bytes)                            | read-write | No       | The attribute's static value (if it is a static attribute).
| **template_id**          | Integer                                                 | read-write | No       | From which template did this attribute come from.
| **type**                 | String (length of 32 bytes)                             | read-write | Yes      | Attribute type (`static`, `dynamic`, `actuator`).
| **updated**              | DateTime (with timezone and µs precision) in ISO format | read-only  | No       | Attribute last update time.
| **value_type**           | String (length of 32 bytes)                             | read-write | Yes      | Attribute value type (`string`, `float`, `integer`, `geo`).

All attributes that are read/write can be used when creating or updating the device. All of them are
returned when retrieving device data.

An example of such structure would be:

```json
"attrs": {
  "1": [
    {
      "label": "rain",
      "value_type": "float",
      "template_id": "1",
      "id": 1,
      "static_value": "",
      "type": "dynamic",
      "created": "2020-09-16T14:50:09.297163+00:00",
      "is_static_overridden": false
    },
    {
      "label": "mark",
      "value_type": "string",
      "template_id": "1",
      "id": 2,
      "static_value": "efac",
      "type": "static",
      "created": "2020-09-16T14:58:25.905376+00:00",
      "is_static_overridden": false
    }
  ]
}
```

### **Template**

All devices are based on a **template**, which can be thought as a blueprint: all devices built
using the same template will have the same characteristics. Templates in dojot have one label (any
alphanumeric sequence), a list of attributes which will hold all the device emitted information, and
optionally a few special attributes which will indicate how the device communicates, including
transmission methods (protocol, ports, etc.) and message formats.

In fact, templates can represent not only *device models*, but it can also abstract a *class of
devices*. For instance, we could have one template to represent all thermometers that will be used
in dojot. This template would have also only one attribute called `temperature`. While creating the
device, the user would select its *physical template*, let's say *TexasInstr882*, and the
`thermometer` template. The user would have also to add the translation instructions in order to map
the temperature reading that will be sent from the device to the `temperature` attribute.

In order to create a device, a user selects which templates are going to compose this new device.
All their attributes are merged together and associated to it - they are tightly linked to the
original template so that any template update will reflect all associated devices.

The information model used for templates is:

| Attribute        | Type                                                    | Mode       | Required | Description
| ---------------- | ------------------------------------------------------- | ---------- | -------- | --------------------------------------------------------------------------------
| **attrs**        | Map of attributes                                       | read-write | No       | Merges the `config_attrs` and the `data_attrs` parameters.
| **config_attrs** | Map of attributes                                       | read-write | No       | Stores attributes with the type `meta`.
| **created**      | DateTime (with timezone and µs precision) in ISO format | read-only  | No       | Device creation time.
| **data_attrs**   | Map of attributes                                       | read-write | No       | Stores attributes with the types `dynamic`, `static` and `actuator`.
| **id**           | String (length of 8 bytes)                              | read-write | No       | Unique identifier for the template.
| **label**        | String (length of 128 bytes)                            | read-write | Yes      | An user-defined label to facilitate the template's identification.
| **updated**      | DateTime (with timezone and µs precision) in ISO format | read-only  | No       | Device last update time.

An example template structure:

```json
{
  "label": "teste",
  "attrs": [
    {
      "label": "rain",
      "value_type": "float",
      "template_id": "1",
      "id": 1,
      "static_value": "",
      "type": "dynamic",
      "created": "2020-09-16T14:50:09.297163+00:00"
    },
    {
      "label": "mark",
      "value_type": "string",
      "template_id": "1",
      "id": 2,
      "static_value": "efac",
      "type": "static",
      "created": "2020-09-16T14:58:25.905376+00:00"
    }
  ],
  "data_attrs": [
    {
      "label": "rain",
      "value_type": "float",
      "template_id": "1",
      "id": 1,
      "static_value": "",
      "type": "dynamic",
      "created": "2020-09-16T14:50:09.297163+00:00"
    },
    {
      "label": "mark",
      "value_type": "string",
      "template_id": "1",
      "id": 2,
      "static_value": "efac",
      "type": "static",
      "created": "2020-09-16T14:58:25.905376+00:00"
    }
  ],
  "id": 1,
  "config_attrs": [ ],
  "created": "2020-09-16T14:50:09.292714+00:00"
}
```

All attributes that are read-write can be used when creating or updating the template. All of them
are returned when retrieving device data. You might also notice some new attributes:
- `data_attrs`: stores attributes with the types `dynamic`, `static` and `actuator`.
- `config_attrs`: stores attributes with the type `meta`. You can only create this type of attribute
  via API, check its [documentation](https://dojot.github.io/device-manager/apiary_latest.html) for
  more details.

These two parameters are merged in the `attrs`.

## Events

There are some messages that are published by Device Manager to Kafka. These messages are
notifications of device management operations, and they can be consumed by any component interested
in them, such as IoT agents.

For more information on the parameters of the messages, please refer to the [Device Manager concepts
topic](#concepts).

__NOTE THAT__ all messages reside in Kafka's `dojot.device-manager.device` topic.

The events that are emitted by the Device Manager are:

- `configure`
- `create`
- `remove`
- `update`
- `template.update` **deprecated**

### **Event: `configure`**

This message is published whenever a device must be configured. Its payload is:

```json
{
  "event": "configure",
  "meta": {
    "service": "admin",
    "timestamp": 1557493697
  },
  "data" : {
    "id" : "efac",
    "attrs": {
      "target_temperature" : 23.5
    }
  }
}
```

The attribute actually used by the device would be `target_temperature` so that it can, for example,
correctly adjust the temperature. It’s up to the receiver of this message (an IoT agent, for
instance) to properly send the configuration to the device.

### **Event: `create`**

This message is published whenever a new device is created. Its payload is:

```json
{
  "event": "create",
  "data": {
    "label": "teste",
    "templates": [
      1
    ],
    "id": "e06357",
    "created": "2020-09-16T14:50:34.749230+00:00",
    "attrs": {
      "1": [
        {
          "label": "rain",
          "value_type": "float",
          "template_id": "1",
          "id": 1,
          "static_value": "",
          "type": "dynamic",
          "created": "2020-09-16T14:50:09.297163+00:00",
          "is_static_overridden": false
        }
      ]
    }
  },
  "meta": {
    "service": "admin"
  }
}
```


### **Event: `remove`**

This message is published whenever a device is removed. Its payload is:

```json
{
  "event": "remove",
  "meta": {
    "service": "admin"
  },
  "data": {
    "id": "efac"
  }
}
```

### **Event: `update`**

This message is published whenever a new device is directly or indirectly updated. The `indirectly
updated` case happens when a template associated with the device is updated. Its payload looks very
similar to device creation:

```json
{
  "event": "update",
  "data": {
    "label": "teste",
    "templates": [
      1
    ],
    "id": "e06357",
    "created": "2020-09-16T14:50:34.749230+00:00",
    "attrs": {
      "1": [
        {
          "label": "rain",
          "value_type": "float",
          "template_id": "1",
          "id": 1,
          "static_value": "",
          "type": "dynamic",
          "created": "2020-09-16T14:50:09.297163+00:00",
          "is_static_overridden": false
        },
        {
          "label": "mark",
          "value_type": "string",
          "template_id": "1",
          "id": 2,
          "static_value": "efac",
          "type": "static",
          "created": "2020-09-16T14:58:25.905376+00:00",
          "is_static_overridden": false
        }
      ]
    }
  },
  "meta": {
    "service": "admin"
  }
}
```

### **Event: `template.update` (deprecated)**

__IMPORTANT__: this event is deprecated and can be removed from the platform soon.

This event is emitted every time a template is updated. It contains all the affected devices and the
new model for that template. Its payload is:

```json
{
  "event": "template.update",
  "data": {
    "affected": [
      "e06357"
    ],
    "template": {
      "label": "teste",
      "attrs": [
        {
          "label": "rain",
          "value_type": "float",
          "template_id": "1",
          "id": 1,
          "static_value": "",
          "type": "dynamic",
          "created": "2020-09-16T14:50:09.297163+00:00"
        },
        {
          "label": "mark",
          "value_type": "string",
          "template_id": "1",
          "id": 2,
          "static_value": "efac",
          "type": "static",
          "created": "2020-09-16T14:58:25.905376+00:00"
        }
      ],
      "data_attrs": [
        {
          "label": "rain",
          "value_type": "float",
          "template_id": "1",
          "id": 1,
          "static_value": "",
          "type": "dynamic",
          "created": "2020-09-16T14:50:09.297163+00:00"
        },
        {
          "label": "mark",
          "value_type": "string",
          "template_id": "1",
          "id": 2,
          "static_value": "efac",
          "type": "static",
          "created": "2020-09-16T14:58:25.905376+00:00"
        }
      ],
      "id": 1,
      "config_attrs": [ ],
      "created": "2020-09-16T14:50:09.292714+00:00"
    }
  },
  "meta": {
    "service": "admin"
  }
}
```
