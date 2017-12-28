# DeviceManager

[![License badge](https://img.shields.io/badge/license-GPL-blue.svg)](https://opensource.org/licenses/GPL-3.0)
[![Docker badge](https://img.shields.io/docker/pulls/dojot/iotagent-json.svg)](https://hub.docker.com/r/dojot/device-manager/)


This implements a service to manage devices and their configuration

## How to run
```shell
python setup.py develop
gunicorn device-manager.app:app
```

## Using curl to manage devices

### Creating device
```shell
 curl -X POST http://0:5000/devices --data "device-id=dev003" --data "name=thermometer03" --data "location=entrance" --data "purchase-date=02.02.17"
 curl -X POST http://0:5000/devices --header 'Content-Type:application/json' --data '{ "device-id" : "dev002", "name": "barometer-01"}'
 ```

### Retrieving device

```shell
curl -X GET http://0:5000/devices
curl -X GET http://0:5000/devices/dev002
 ```

### Updating device info
```shell
curl -X PUT http://0:5000/devices/dev003 --data "name=thermometer01" --data "location=hallway"
```
### Deleting device
This will also remove any associated icon

```shell
curl -X DELETE http://0:5000/devices/dev003
```

### Uploading and removing icons

```shell
 curl -X PUT http://0:5000/devices/dev002/icon -F "icon=@sample-icons/icon.svg"
 curl -X DELETE http://0:5000/devices/dev002/icon
```
