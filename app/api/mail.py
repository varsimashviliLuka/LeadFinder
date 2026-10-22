from flask import current_app
from flask_restx import Namespace, Resource, fields

from app.api.common import json_body
from app.services import mailer

ns = Namespace("mail", description="Your Gmail account for sending emails to leads")

mail_settings_model = ns.model(
    "MailSettings",
    {
        "configured": fields.Boolean(readonly=True),
        "address": fields.String(description="Your Gmail address"),
        "sender_name": fields.String(description="Name shown to the recipient"),
    },
)

mail_settings_input_model = ns.model(
    "MailSettingsInput",
    {
        "address": fields.String(required=True),
        "app_password": fields.String(description="16-letter Gmail App Password; leave empty to keep the saved one"),
        "sender_name": fields.String,
    },
)

mail_test_model = ns.model("MailTestResult", {"sent_to": fields.String})


@ns.route("/settings")
class MailSettings(Resource):
    @ns.marshal_with(mail_settings_model)
    def get(self):
        """Whether Gmail is connected (the password is never returned)."""
        return mailer.public_settings(current_app.config)

    @ns.expect(mail_settings_input_model)
    @ns.marshal_with(mail_settings_model)
    def put(self, **_):
        """Sign in to Gmail to check the details, then save them."""
        try:
            return mailer.save_settings(current_app.config, json_body(ns))
        except mailer.MailError as exc:
            ns.abort(400, str(exc))

    @ns.response(204, "Disconnected")
    def delete(self):
        """Forget the saved Gmail address and App Password."""
        mailer.delete_settings(current_app.config)
        return "", 204


@ns.route("/test")
class MailTest(Resource):
    @ns.marshal_with(mail_test_model)
    def post(self):
        """Send a test email to yourself."""
        settings = mailer.public_settings(current_app.config)
        if not settings["configured"]:
            ns.abort(400, "Connect your Gmail first")
        try:
            mailer.send_email(
                current_app.config,
                settings["address"],
                "Lead Finder test email",
                "It works! Emails to your leads will be sent from this address.",
            )
        except mailer.MailError as exc:
            ns.abort(502, str(exc))
        return {"sent_to": settings["address"]}
