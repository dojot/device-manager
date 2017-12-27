========================
Device manager internals
========================


Information model for device and templates.

Device:
 - id: string (read-only)
 - label: string (read-write, required)
 - created: DateTime (read-only)
 - updated: DateTime (read-only)
 - templates: [ string (template ID) ] (read-write)
 - attrs: [ Attributes ] (read-only)

Template:
 - id: integer (read-write)
 - label: string (read-write, required)
 - created: DateTime (read-only)
 - updated: DateTime (read-only)
 - attrs: [ Attributes ] (read-write)

Attributes: 
 - id: integer (read-write)
 - label: string (read-write, required)
 - created: DateTime (read-only)
 - updated: DateTime (read-only)
 - type: string (read-write, required)
 - value_type: string (read-write, required)
 - static_value: string (read-write)
 - template_id: string (read-write)