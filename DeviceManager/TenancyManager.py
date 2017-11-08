import base64
import json
from sqlalchemy.sql import exists, select, text
from utils import HTTPRequestError

def decode_base64(data):
    """Decode base64, padding being optional.

    :param data: Base64 data as an ASCII byte string
    :returns: The decoded byte string.

    """
    missing_padding = len(data) % 4
    if missing_padding != 0:
        data += b'='* (4 - missing_padding)
    return base64.decodestring(data)

def get_allowed_service(token):
    """
        Parses the authorization token, returning the service to be used when
        configuring the FIWARE backend

        :param token: JWT token to be parsed
        :returns: Fiware-service to be used on API calls
        :raises ValueError: for invalid token received
    """
    if not token or len(token) == 0:
        raise ValueError("Invalid authentication token")

    payload = token.split('.')[1]
    try:
        data = json.loads(decode_base64(payload))
        return data['service']
    except Exception as ex:
        raise ValueError("Invalid authentication token payload - not json object", ex)

    return None

def create_tenant(tenant, db):
    db.session.execute("create schema \"%s\";" % tenant)

def switch_tenant(tenant, db):
    db.session.execute("SET search_path TO %s" % tenant)
    db.session.commit()

def init_tenant(tenant, db):
    query = exists(select([text("schema_name")])
                   .select_from(text("information_schema.schemata"))
                   .where(text("schema_name = '%s'" % tenant)))
    tenant_exists = db.session.query(query).scalar()

    if not tenant_exists:
        create_tenant(tenant, db)
        switch_tenant(tenant, db)
        db.create_all()
    else:
        switch_tenant(tenant, db)


def init_tenant_context(request, db):
    try:
        token = request.headers['authorization']
    except KeyError:
        raise HTTPRequestError(401, "No authorization token has been supplied")

    tenant = get_allowed_service(token)
    init_tenant(tenant, db)
    return tenant
