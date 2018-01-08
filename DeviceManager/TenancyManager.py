import base64
import json
from sqlalchemy.sql import exists, select, text
from utils import HTTPRequestError


def install_triggers(db):
    query = """
        -- template update/creation checks

        CREATE FUNCTION validate_device_attrs() returns trigger as $$
        DECLARE
          conflict_count int;
        BEGIN
          conflict_count := (
            select count(*) from attrs as a
            left join device_template as dt on a.template_id = dt.template_id
            left join devices as d on d.id = dt.device_id
            where dt.template_id != NEW.template_id and
                  dt.device_id in (select device_id from device_template where template_id = NEW.template_id) and
                  a.label = NEW.label and a.type = NEW.type
          );
          IF (conflict_count != 0) THEN
            RAISE 'Attribute % (%) has standing conflicts', NEW.label, NEW.id using ERRCODE = 'unique_violation';
          END IF;
          RETURN NEW;
        END;
        $$ language plpgsql;

        CREATE TRIGGER validate_device_attrs_trigger BEFORE INSERT OR UPDATE ON attrs
        FOR EACH ROW EXECUTE PROCEDURE validate_device_attrs();

        -- template assignment checks

        CREATE FUNCTION validate_device() returns trigger as $$
        DECLARE
          conflict_count int;
        BEGIN
          conflict_count := (
            select count(*) from (
              select * from attrs as attr
              inner join device_template as dt on attr.template_id = dt.template_id
              where dt.device_id = NEW.device_id
            ) as curr
            inner join attrs as nattrs on curr.label = nattrs.label and curr.type = nattrs.type and nattrs.template_id = NEW.template_id
          );
          IF (conflict_count != 0) THEN
            RAISE 'Template (%) cannot be added to device (%) as it has standing attribute conflicts', NEW.template_id, NEW.device_id
            using ERRCODE = 'unique_violation';
          END IF;
          RETURN NEW;
        END;
        $$ language plpgsql;

        CREATE TRIGGER validate_device_trigger BEFORE INSERT OR UPDATE ON device_template
        FOR EACH ROW EXECUTE PROCEDURE validate_device();
    """
    db.session.execute(query)


def decode_base64(data):
    """Decode base64, padding being optional.

    :param data: Base64 data as an ASCII byte string
    :returns: The decoded byte string.

    """
    missing_padding = len(data) % 4
    if missing_padding != 0:
        data += b'=' * (4 - missing_padding)
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
        install_triggers(db)
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
