#contract=UploadService
#version=0.1
import sys
import os
import uuid
import tempfile, time, json
from flask import Flask, send_from_directory, Response, request, abort
from werkzeug.utils import secure_filename
from decelium_wallet.commands.BaseService import BaseService
from decelium_wallet.commands.BaseData import BaseData
from nodejobs.jobs import Jobs
import requests
from typing import Protocol, runtime_checkable
from decelium_core_data.DDBFolder import DDBFolder


class UploadService(BaseService):

    @runtime_checkable
    class DataReadable(Protocol):
        def read(self, size: int = -1):
            pass
        def close(self) -> None:
            pass
    
    class tClientUploadData(BaseData):
        f_token = "token"
        f_stream = "stream"
        f_filename = "filename"        
        f_filepath = "filepath"        
        def get_keys(self):
            return {
                self.f_token: str,
                self.f_stream: UploadService.DataReadable,
                self.f_filename: str,
                self.f_filepath: str
            }, {}
        
        def do_validation(self,key,value):
            print(f"Validating  NewArgs- {key}:{value}")
            if key == 'stream' and  value == None:
                s = self.GetDirtyDict()
                #print(s)
                #s = self
                value = open(os.path.join(s[self.f_filepath],s[self.f_filename]),"r")
            if key == 'stream' and  type(value) == str:
                value = io.BytesIO(value.encode('utf-8'))
            return value,""

    class tHostAddress(BaseData):
        f_protocol = "protocol"
        f_port = "port"
        f_host = "host"        
        f_url = "url"        
        def get_keys(self):
            return {
                self.f_protocol: str,
                self.f_port: str,
                self.f_host: str,
                self.f_url: str,
            }, {}
        def getUrl(self):
            URL = f"{self[self.f_protocol]}://{self[self.f_host]}:{self[self.f_port]}/{self[self.f_url]}"
            return URL
    
    
    class tHostSpec(tHostAddress):
        #f_protocol = "protocol"
        #f_port = "port"
        #f_host = "host"        
        #f_url = "url"        
        #
        f_web_html_dir = "web_html_dir"
        f_upload_dir = "upload_dir"
        f_tokens   = "tokens"
        
        def get_keys(self):
            required = {
                self.f_web_html_dir: str,
                self.f_tokens: str,
                self.f_upload_dir: str
            }
            ha_required, _ = super().get_keys()
            # Now update 'required' in-place.
            required.update(ha_required)
            return required, {}
        
    @classmethod
    def get_command_map(cls):
        return {
            "launch": {
                "required_args": [],
                "method": cls._cmd_launch,
            },
            "logs": {
                "required_args": [],
                "method": cls._cmd_logs,
            },
            "list": {
                "required_args": [],
                "method": cls._cmd_list,
            },
            "test": {
                "required_args": [],
                "method": cls._cmd_test,
            },            
            "upload_file": {
                "required_args": [],
                "method": cls._upload_file,
            },
            "start": {
                "required_args": [],
                "method": cls._cmd_start,
            },
            "stop": {
                "required_args": [],
                "method": cls._cmd_stop,
            },
        }

    @classmethod
    def _upload_file(cls,**kwargs):
        # Prepare Data
        s = cls.tHostAddress(kwargs)     
        #serverDat = tHostAddress(kwargs)
        d = cls.tClientUploadData(kwargs)

        stream = d[d.f_stream]
        if (type(stream) == str):
            stream = open(stream,'r')

        files = {"file": (d[d.f_filename], stream)}
        headers = {"Upload-Token": d[d.f_token]}
        data = {"filepath": d[d.f_filepath]}  # Additional form field
        # See: _flask_server_upload_file next
        resp = requests.post(s.getUrl(), 
                                headers=headers, 
                                files=files,
                                data=data)

        print(resp)  # 201 on success

    @classmethod
    def _upload_file_p2(cls,request,hostSpec:dict):
        hostSpec= cls.tHostSpec (hostSpec)
        token = request.headers.get("Upload-Token")
        if token not in hostSpec[hostSpec.f_tokens]:
            abort(401, "Invalid or missing Upload-Token")

        if "file" not in request.files:
            abort(400, "Missing file part")

        f = request.files["file"]
        if f.filename == "":
            abort(400, "Empty filename")
        client_filepath = request.form.get(cls.tClientUploadData.f_filepath)
        filename = f"{uuid.uuid4().hex}.dat"
        #os.makedirs(hostSpec[hostSpec.f_upload_dir], exist_ok=True)
                 
        #save_path = os.path.join(hostSpec[hostSpec.f_upload_dir],filename)
        #f.save(save_path)

        obj = DDBFolder.create_file(
            {
                #'owner_id': "12345",
                #'parent_id': "",
                #'name': f"test_file_{i}",
                'filename': f.filename,
                'stream': f,
            },
            {
                'file_root': hostSpec[hostSpec.f_upload_dir],
                'path': 'uploads/',
                'do_overwrite':True,
            }
        )

        #cls.on_upload(save_path)
        return ("", 201)        


    @classmethod
    def _cmd_start(cls, **kwargs):
        ha = cls.tHostSpec(kwargs)
        cmdDict = BaseService.flatten(kwargs)
        cmdArgs = BaseService.to_arg_string(cmdDict)
        print(json.dumps(cmdDict,indent=4))
        jobs = Jobs()
        run_command = "python3 "+os.path.abspath(__file__)+" launch "+cmdArgs
        print(run_command)
        result = jobs.run(command= run_command, job_name="http_upload", cwd = os.getcwd(), envs = os.environ.copy())
        return jobs.list_status({'dirname':"http_upload"})
    
    @classmethod
    def _cmd_list(cls, **kwargs):
        jobs = Jobs()
        return jobs.list_status({'dirname':"http_upload"})

    @classmethod
    def _cmd_logs(cls, **kwargs):
        jobs = Jobs()
        return jobs.job_logs(job_name="http_upload")


    @classmethod
    def _cmd_stop(cls,  **kwargs):
        jobs = Jobs()
        result = jobs.stop(job_name="http_upload")
        return jobs.list_status({'dirname':"http_upload"})
        
    @classmethod
    def on_upload(cls,pth):
        print("uploaded path "+pth)

    @classmethod
    def _cmd_launch(cls, **kwargs):
        ha = cls.tHostSpec(kwargs)

        root_dir = ha[ha.f_web_html_dir]
        upload_dir = ha[ha.f_upload_dir]
        port = ha[ha.f_port]
        host = ha[ha.f_host]
        tokens = ha[ha.f_tokens]
        upload_dir = ha[ha.f_upload_dir]
        upload_url = ha[ha.f_url]

        # Convert args
        port = int(port)
        VALID_TOKENS = set(tokens.split(","))
        os.makedirs(upload_dir, exist_ok=True)

        # Build Flask app
        app = Flask(__name__, static_url_path=None)
        app.config.from_object(__name__)

        @app.route("/", methods=["GET", "POST"])
        @app.route("/<path:u_path>", methods=["GET", "POST"])
        def index(u_path="/"):
            full = os.path.join(os.getcwd(), root_dir, u_path.lstrip("/"))
            if os.path.isfile(full):
                return send_from_directory(os.path.join(os.getcwd(), root_dir), u_path)
            return Response(f"File not found at: {full}", status=404)

        @app.route(upload_url, methods=["POST"])
        def upload():
            return cls._upload_file_p2(request,ha)

        # Run Flask
        print(f"Starting upload server on {host}:{port}")
        app.run(host=host, port=port)
        return 0

    @classmethod
    def _cmd_test(cls):
        # python simple_upload_host.py upload_example !fileSpec=./test_specs/testUploadSpec.json !serverAddy=./test_specs/hostAddress.json
        original_cwd = os.getcwd()
        #hostSpec = cls.tHostSpec(kwargs['hostSpec'])
        #serverDat = cls.tHostSpec(kwargs['serverDat'])
        #file = cls.tHostSpec(kwargs['file'])

        hostSpec = cls.tHostSpec({
             cls.tHostSpec.f_web_html_dir:"./server/static_html",
             cls.tHostSpec.f_upload_dir:"./server/flask_uploaded",
             cls.tHostSpec.f_url:"/do_upload",
             cls.tHostSpec.f_port:"5000",
             cls.tHostSpec.f_host:"0.0.0.0",
             cls.tHostSpec.f_protocol:"http",
             cls.tHostSpec.f_tokens:"<<DSH_CLIENT_TOKEN_LIST>>"
        })
        
        serverDat = cls.tHostAddress({
             cls.tHostAddress.f_protocol:hostSpec[hostSpec.f_protocol],
             cls.tHostAddress.f_port:hostSpec[hostSpec.f_port],
             cls.tHostAddress.f_host:"localhost",
             cls.tHostAddress.f_url:hostSpec[hostSpec.f_url],
        })     

        file = cls.tClientUploadData({
                cls.tClientUploadData.f_token:"<<DSH_CLIENT_TOKEN>>",
                cls.tClientUploadData.f_filename:"demo_file_2.txt",
                cls.tClientUploadData.f_filepath:"./client/",
                cls.tClientUploadData.f_stream : open("demo_file_2.txt", "r")})
        
        try:
            #os.chdir(tmpdir)
            #print("[TEST] Changed working directory to:", tmpdir)
            filename = os.path.join(file[file.f_filepath],file[file.f_filename])
            os.makedirs(file[file.f_filepath], exist_ok=True)            
            print("[TEST] Created demo file:", os.path.join(file[file.f_filepath],file[file.f_filename]))
            with open(filename, "w") as f:
                f.write("This is a sample content for upload testing.\n")                

            start_result = UploadService.run(**{"__command":['start'], **hostSpec})
            time.sleep(3)        

            list_result = UploadService.run(__command=['list'])
            print(list_result)
            if 'http_upload' in list_result and list_result['http_upload']['status'] == 'running':
                print("[TEST] Start command running:", start_result)
            else:
                print("[FAILED] COULD NOT START SERVER")
                return 0

            UploadService.run(**{ "__command":['upload_file'], **file, **serverDat})            
            print("[TEST] Upload example executed.")        

            time.sleep(1)        
            print("[TEST] Checking for upload directory at:", hostSpec[hostSpec.f_upload_dir])

            assert os.path.exists( hostSpec[hostSpec.f_upload_dir]), f"Uploads directory not found: { hostSpec[hostSpec.f_upload_dir]}"
            uploaded_files = os.listdir( hostSpec[hostSpec.f_upload_dir])
            print("[TEST] Uploaded file(s) found:", uploaded_files)
            assert any(fname.endswith(".dat") for fname in uploaded_files), "No .dat file uploaded"        

            for fname in uploaded_files:
                os.remove(os.path.join(uploads_dir, fname))

            remaining = os.listdir(hostSpec[hostSpec.f_upload_dir])
            print("[TEST] Uploads folder after cleanup:", remaining)
            assert len(remaining) == 0, "Not all uploaded files were removed"       
            
            stop_result = UploadService.run(__command=['stop'])
            print("[TEST] Stop command returned:", stop_result)
            print("[TEST] Upload service test PASSED.")
        
        finally:
            os.chdir(original_cwd)
            #shutil.rmtree(tmpdir)
            print("[TEST] Cleaned up temporary working directory.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()     
    UploadService.run_cli()
# python simple_upload_host.py launch !server=./test_specs/hostSpec.json 
# python simple_upload_host.py upload_file !fileSpec=./test_specs/testUploadSpec.json !serverAddy=./test_specs/hostAddress.json
# python simple_upload_host.py test
# python simple_upload_host.py test
