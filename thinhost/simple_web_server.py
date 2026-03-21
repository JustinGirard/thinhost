from nodejobs.dependencies.BaseService import BaseService
from nodejobs.dependencies.BaseData import BaseData
from thinhost.simple_upload_host import jsondateencode_local
from flask import Flask, send_from_directory, Response, request
from flask_cors import CORS
import os


class SimpleWebServer(BaseService):
    class Command(BaseData):
        f_command_id = "command_id"
        f_data = "data"

        def get_keys(self):
            return {
                self.f_command_id: str,
                self.f_data: dict,
            }, {}

    class tHostSpec(BaseData):
        f_host = "host"
        f_port = "port"
        f_command_uri = "command_uri"
        f_public_root = "public_root"
        f_cwd = "cwd"

        def get_keys(self):
            required = {
                self.f_host: str,
                self.f_port: str,
                self.f_command_uri: str,
                self.f_public_root: str,
            }
            optional = { self.f_cwd: str }
            return required, optional

    c_index_file = "index.html"
    c_cors_path = r"/*"
    c_cors_origins_key = "origins"
    c_cors_any = "*"

    @classmethod
    def get_command_map(cls):
        return {
            "launch": { "required_args": [], "method": cls._cmd_launch },
        }

    @classmethod
    def _after_launch_endpoints(cls, app, hostSpec):
        pass

    @classmethod
    def _cmd_launch(cls, **kwargs):
        cls.currentHa = cls.tHostSpec(kwargs)
        cwd_start = os.getcwd()
        root_dir_raw = cls.currentHa[cls.currentHa.f_public_root]
        cmd_uri = cls.currentHa[cls.currentHa.f_command_uri]
        if not os.path.isdir(root_dir_raw): raise Exception(f"public_root does not exist: {root_dir_raw}")
        if not cmd_uri.startswith("/"): raise Exception("command_uri must start with '/'")
        os.chdir(root_dir_raw)
        root_dir = os.getcwd()

        app = Flask(__name__, static_folder=None, static_url_path=None)
        app.config.from_object(__name__)
        CORS(app, resources={cls.c_cors_path: {cls.c_cors_origins_key: cls.c_cors_any}})

        @app.route("/", methods=["GET", "POST"])
        @app.route("/<path:u_path>", methods=["GET", "POST"])
        def index(u_path="/"):
            rel_path = u_path.lstrip("/")
            full = os.path.join(root_dir, rel_path)
            if os.path.isfile(full): return send_from_directory(root_dir, rel_path)
            if os.path.isdir(full):
                index_path = os.path.join(full, cls.c_index_file)
                if os.path.isfile(index_path): return send_from_directory(full, cls.c_index_file)
            root_index = os.path.join(root_dir, cls.c_index_file)
            if os.path.isfile(root_index): return send_from_directory(root_dir, cls.c_index_file)
            msg = (
                f"File not found: {rel_path}\n"
                f"cwd_start: {cwd_start}\n"
                f"public_root: {root_dir_raw}\n"
                f"root_dir: {root_dir}\n"
                f"full: {full}"
            )
            return Response(msg, status=404)

        @app.route(cmd_uri, methods=["POST"])
        def process_command():
            cmd = cls.Command(request.get_json())
            resp = cls.run(__command=[cmd[cmd.f_command_id]], **cmd[cmd.f_data])
            return (jsondateencode_local.dumps(resp), 201)

        cls._after_launch_endpoints(app, cls.currentHa)
        app.run(host=cls.currentHa[cls.currentHa.f_host], port=int(cls.currentHa[cls.currentHa.f_port]))
        return "ok"


if __name__ == "__main__":
    SimpleWebServer.run_cli()
