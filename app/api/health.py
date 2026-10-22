from flask_restx import Namespace, Resource, fields
from sqlalchemy import text

from app.extensions import db

ns = Namespace("health", description="Service health checks")

health_model = ns.model(
    "Health",
    {
        "status": fields.String(example="ok"),
        "database": fields.String(example="ok"),
    },
)


@ns.route("")
class Health(Resource):
    @ns.marshal_with(health_model)
    def get(self):
        try:
            db.session.execute(text("SELECT 1"))
            database = "ok"
        except Exception:
            database = "error"
        status = "ok" if database == "ok" else "degraded"
        return {"status": status, "database": database}, 200 if status == "ok" else 503
