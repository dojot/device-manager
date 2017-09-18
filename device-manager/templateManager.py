import json
import os
from time import time
from flask import Flask
from flask import request
from flask import make_response
from flask import Blueprint
import pymongo
from utils import CollectionManager, formatResponse, get_allowed_service
import utils

template = Blueprint('template', __name__)
db = CollectionManager('device_management')
def get_mongo_collection(token):
    """
        Returns a pymongo collection object pointing to the service-enabled
        collection to be used

        :param token: JWT token received
        :returns: pymongo collection object
        :raises ValueError: Invalid token received
    """
    service = get_allowed_service(token)
    collection = db("tpl_service_%s" % service)
    return collection

def remove_icons(deviceid):
    if os.path.isfile('./icons/{}.svg'.format(deviceid)):
        os.remove('./icons/{}.svg'.format(deviceid))

@template.route('/template', methods=['GET'])
def get_templates():
    collection = get_mongo_collection(request.headers['authorization'])
    if ('limit' in request.args.keys()):
        try:
            cursor = collection.find({}, {'_id': False}, limit=int(request.args['limit']));
        except (TypeError, ValueError):
            return formatResponse(400, 'limit must be an integer value')
    else:
        cursor = collection.find({}, {'_id': False});

    sort = []
    if 'sortAsc' in request.args.keys():
        sort.append((request.args['sortAsc'], pymongo.ASCENDING))
    if 'sortDsc' in request.args.keys():
        sort.append((request.args['sortDsc'], pymongo.DESCENDING))
    if len(sort) > 0:
        cursor.sort(sort)

    templateList = []
    for d in cursor:
        templateList.append(d)

    all_templates = {"templates" : templateList}
    return make_response(json.dumps(all_templates), 200)

@template.route('/template', methods=['POST'])
def create_template():
    collection = get_mongo_collection(request.headers['authorization'])

    template_data = {}
    if request.mimetype == 'application/x-www-form-urlencoded':
        template_data = request.form
    elif request.mimetype == 'application/json':
        try:
            template_data = json.loads(request.data)
        except ValueError:
            return formatResponse(400, 'Failed to parse payload as JSON')


    # TODO this is awful, makes me sad, but for now also makes demoing easier
    # We might want to look into an auto-configuration feature using the service
    # and device name on automate to be able to remove this
    _attempts = 0
    template_data['id'] = ''
    while _attempts < 10 and len(template_data['id']) == 0:
        new_id = utils.create_id()
        if not collection.find_one({'id' : new_id}):
            template_data['id'] = new_id
            break
    if not len(template_data['id']):
        return utils.formatResponse(500, 'failed to generate unique id')

    template_data['created'] = time()
    template_data['updated'] = time()
    collection.insert_one(template_data.copy())
    result = {'message': 'template created', 'template': template_data}
    return make_response(json.dumps(result))

@template.route('/template/<templateid>', methods=['GET'])
def get_template(templateid):
    collection = get_mongo_collection(request.headers['authorization'])
    template = collection.find_one({'id' : templateid}, {"_id" : False})
    if template is None:
        return formatResponse(404, 'Given template was not found')

    return make_response(json.dumps(template), 200)

@template.route('/template/<templateid>', methods=['DELETE'])
def remove_template(templateid):
    collection = get_mongo_collection(request.headers['authorization'])
    result = collection.delete_one({'id' : templateid})
    if result.deleted_count < 1:
        return formatResponse(404, 'Given template was not found')

    remove_icons(templateid)
    return formatResponse(200)

@template.route('/template/<templateid>', methods=['PUT'])
def update_template(templateid):
    collection = get_mongo_collection(request.headers['authorization'])
    template_data = None
    if request.mimetype == 'application/x-www-form-urlencoded':
        template_data = request.form
    elif request.mimetype == 'application/json':
        try:
            template_data = json.loads(request.data)
        except ValueError:
            return formatResponse(400, 'Failed to parse payload as JSON')

    if 'id' not in template_data.keys():
        template_data["id"] = templateid

    template_data['updated'] = time()
    result = collection.replace_one({'id' : templateid}, template_data)
    if result.matched_count != 1:
        return formatResponse(404, 'Given template was not found')

    return formatResponse(200)

@template.route('/template/<templateid>/icon', methods=['PUT', 'GET', 'DELETE'])
def manage_icon(templateid):
    collection = get_mongo_collection(request.headers['authorization'])
    template = collection.find_one({'id' : templateid}, {"_id" : False})
    if template is None:
        return formatResponse(404, 'Given template was not found')

    if request.method == 'PUT':
        icon_file = request.files['icon']
        # For now just svg
        icon_filename = './icons/{}.svg'.format(templateid)
        icon_file.save(icon_filename)
        if ('has_icon' not in template.keys()) or (template["has_icon"] == False):
            template["has_icon"] = True
            collection.replace_one({'id' : templateid}, template)
        return formatResponse(201)
    elif request.method == 'GET':
        if os.path.isfile('./icons/{}.svg'.format(templateid)):
            icon_file = open('./icons/{}.svg'.format(templateid), 'r')
            icon_str = icon_file.read()
            resp = make_response(icon_str, 200)
            # For now just svg
            resp.headers['Content-Type'] = 'image/svg+xml'
            return resp
        else:
            return formatResponse(204, "Given template has no icon assigned")
    elif request.method == 'DELETE':
        remove_icons(templateid)
        template["has_icon"] = False
        collection.replace_one({'id' : templateid}, template)
        return formatResponse(200)

    return formatResponse(400, "Invalid request type")
