from nodejobs.dependencies.BaseService import BaseService
from nodejobs.dependencies.BaseData import BaseData
from thinhost.simple_upload_host import jsondateencode_local
from flask import Flask, send_from_directory, send_file, Response, request, has_request_context
from flask_cors import CORS
import os
import json
import base64


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
    c_http_mode_key = "_mode"
    c_http_mode_rpc = "rpc"
    c_http_mode_html = "html"

    @classmethod
    def get_command_map(cls):
        return {
            "launch": { "required_args": [], "method": cls._cmd_launch },
        }

    @classmethod
    def _after_launch_endpoints(cls, app, hostSpec):
        pass

    @staticmethod
    def encode_http_object_base64url(payload: dict) -> str:
        if not isinstance(payload, dict):
            raise Exception("invalid_payload")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).decode("ascii")
        return encoded.rstrip("=")

    @staticmethod
    def decode_http_object_base64url(encoded: str) -> dict:
        if not isinstance(encoded, str) or not encoded.strip():
            raise Exception("invalid_encoded_payload")
        text = encoded.strip()
        text = text + ("=" * ((4 - (len(text) % 4)) % 4))
        raw = base64.urlsafe_b64decode(text.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise Exception("invalid_encoded_payload")
        return payload

    @classmethod
    def parse_http_request_object(cls, request_obj):
        method = str(getattr(request_obj, "method", "") or "").upper()
        if method == "GET":
            encoded = request_obj.args.get("__encoded")
            if isinstance(encoded, str) and encoded.strip():
                return cls.decode_http_object_base64url(encoded)
            return dict(request_obj.args)
        raw = request_obj.get_json()
        if not isinstance(raw, dict):
            raise Exception("invalid_request_payload")
        return raw

    @classmethod
    def get_request(cls):
        if not has_request_context():
            return {}
        return cls.parse_http_request_object(request)

    @classmethod
    def get_request_data(cls, request_payload: dict = None):
        payload = request_payload if isinstance(request_payload, dict) else cls.get_request()
        if not isinstance(payload, dict):
            return {}
        data = payload.get(cls.Command.f_data)
        return data if isinstance(data, dict) else payload

    @classmethod
    def resolve_http_mode(cls, payload: dict):
        if not isinstance(payload, dict):
            return cls.c_http_mode_rpc
        mode = str(payload.get(cls.c_http_mode_key) or "").strip().lower()
        if mode == cls.c_http_mode_html:
            return cls.c_http_mode_html
        return cls.c_http_mode_rpc

    @classmethod
    def respond_mode_aware(
        cls,
        *,
        request_payload: dict,
        rpc_result,
        rpc_status: int = 200,
        html_file_spec: dict = None,
        html_file_spec_builder=None,
    ):
        mode = cls.resolve_http_mode(request_payload)
        if mode == cls.c_http_mode_html:
            spec = html_file_spec
            if spec is None and callable(html_file_spec_builder):
                spec = html_file_spec_builder(request_payload, rpc_result)
            if not isinstance(spec, dict):
                raise Exception("html_mode_requires_file_spec")
            return cls.serve_file_from(
                root_path=str(spec.get("root_path") or ""),
                cache_path=str(spec.get("cache_path") or ""),
                rel_path=str(spec.get("rel_path") or ""),
                as_attachment=bool(spec.get("as_attachment")),
                download_name=str(spec.get("download_name") or ""),
            )
        return (jsondateencode_local.dumps(rpc_result), int(rpc_status))

    @classmethod
    def serve_file_from(
        cls,
        *,
        root_path: str,
        rel_path: str,
        cache_path: str = "",
        as_attachment: bool = False,
        download_name: str = "",
    ):
        if not isinstance(root_path, str) or not root_path.strip():
            raise Exception("invalid_root_path")
        base_abs = os.path.abspath(root_path.strip())
        if isinstance(cache_path, str) and cache_path.strip():
            base_abs = os.path.abspath(os.path.join(base_abs, cache_path.strip()))
        if not os.path.isdir(base_abs):
            raise Exception("invalid_base_path")

        rel = str(rel_path or "").strip().lstrip("/\\")
        if not rel:
            raise Exception("invalid_rel_path")
        full_abs = os.path.abspath(os.path.join(base_abs, rel))
        if os.path.commonpath([base_abs, full_abs]) != base_abs:
            raise Exception("path_escapes_base")
        if not os.path.isfile(full_abs):
            raise FileNotFoundError("file_not_found")

        name = str(download_name or "").strip() or None
        return send_file(
            full_abs,
            as_attachment=bool(as_attachment),
            download_name=name,
        )

    @classmethod
    def _cmd_launch(cls, **kwargs):
        if has_request_context():
            raise Exception(
                "launch is CLI-only and cannot be invoked via /cmd on a running server"
            )
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

        @app.route(cmd_uri, methods=["GET", "POST"])
        def process_command():
            cmd = cls.Command(cls.get_request())
            resp = cls.run(__command=[cmd[cmd.f_command_id]], **cmd[cmd.f_data])
            return (jsondateencode_local.dumps(resp), 201)

        cls._after_launch_endpoints(app, cls.currentHa)
        app.run(host=cls.currentHa[cls.currentHa.f_host], port=int(cls.currentHa[cls.currentHa.f_port]))
        return "ok"


if __name__ == "__main__":
    SimpleWebServer.run_cli()
