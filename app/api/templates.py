from flask_restx import Namespace, Resource, fields

from app.api.common import json_body
from app.extensions import db
from app.models import MessageTemplate
from app.services.templates import list_templates, save_template

ns = Namespace("templates", description="Reusable WhatsApp / Viber / email messages")

template_model = ns.model(
    "MessageTemplate",
    {
        "id": fields.Integer(readonly=True),
        "name": fields.String(required=True),
        "body": fields.String(required=True, description="{name} and {category} are replaced per lead"),
        "created_at": fields.DateTime(readonly=True),
        "updated_at": fields.DateTime(readonly=True),
    },
)

template_input_model = ns.model(
    "MessageTemplateInput",
    {"name": fields.String(required=True), "body": fields.String(required=True)},
)


def get_or_404(template_id):
    template = db.session.get(MessageTemplate, template_id)
    if template is None:
        ns.abort(404, f"Template {template_id} not found")
    return template


@ns.route("")
class TemplateList(Resource):
    @ns.marshal_list_with(template_model)
    def get(self):
        """All templates, oldest first."""
        return list_templates()

    @ns.expect(template_input_model)
    @ns.marshal_with(template_model, code=201)
    def post(self):
        """Create a template."""
        try:
            template = save_template(None, json_body(ns))
        except ValueError as exc:
            ns.abort(400, str(exc))
        db.session.commit()
        return template, 201


@ns.route("/<int:template_id>")
class TemplateItem(Resource):
    @ns.expect(template_input_model)
    @ns.marshal_with(template_model)
    def patch(self, template_id):
        """Rename or edit a template."""
        template = get_or_404(template_id)
        try:
            save_template(template, json_body(ns))
        except ValueError as exc:
            ns.abort(400, str(exc))
        db.session.commit()
        return template

    @ns.response(204, "Deleted")
    def delete(self, template_id):
        db.session.delete(get_or_404(template_id))
        db.session.commit()
        return "", 204
