# DeviceManager

[![License badge](https://img.shields.io/badge/license-GPL-blue.svg)](https://opensource.org/licenses/GPL-3.0)
[![Docker badge](https://img.shields.io/docker/pulls/dojot/iotagent-json.svg)](https://hub.docker.com/r/dojot/device-manager/)

The DeviceManager handles all operations related to creation, retrieval, update and deletion of devices in dojot.

## Dependencies

DeviceManager has the following dependencies:

- flask (including flask_sqlalchemy)
- psycopg2
- marshmallow
- requests
- gunicorn
- gevent
- json-logging-py
- kakfa-python

But you won't need to worry about installing any of these - they are automatically installed when starting DeviceManager.

## How to run

If you really need to run DeviceManager as a standalone process (without dojot's wonderful docker-compose), you can execute these commands:

```shell
python setup.py develop
gunicorn device-manager.app:app
```

## How to use it

There are a few concepts that must be understood to properly use DeviceManager. Check [this page](concepts.md) to get to know them.

This component listens to HTTP requests at port 5000 - all its endpoints are listed [here](apis.html).
