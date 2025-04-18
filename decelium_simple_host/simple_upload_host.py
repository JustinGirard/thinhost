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

import importlib.util, sys
spec = importlib.util.find_spec("decelium_core_data")
print("spec:", spec)
print("sys.path:", *sys.path, sep="\n  ")


from decelium_core_data.DDBFolder import DDBFolder


class UploadService(BaseService):

    @runtime_checkable
    class DataReadable(Protocol):
        def read(self, size: int = -1):
            pass
        def close(self) -> None:
            pass
    class tTransferProgress(BaseData):
        f_size = "size"
        f_progress = "progress"
        f_status = "status"
        f_data = "data"
        def get_keys(self):
            required = {
                self.f_status: str,
                self.f_size: int,
                self.f_progress: int,
                self.f_data: dict
            }
            optional = {}
            return required, optional 

    class Command(BaseData):
        f_command_id = "command_id"      
        f_executor_id = "executor_id" 
        f_args = "args" 
        f_data = "data" 
        f_auth = "auth" 
        def get_keys(self):
            return {
                self.f_command_id :str,    
                self.f_executor_id :str,
                self.f_args :dict,
                self.f_data :dict,
                self.f_auth :dict
            }, {}
    
    class EntityID(BaseData):
        f_filename = "filename" # THE DESTINATION FILENAME        
        f_filepath = "filepath" # THE DESTINATION FILE PATH
        def get_keys(self):
            return {
                self.f_filename: str,
                self.f_filepath: str,
            }, {}
        
    class tClientUploadData(BaseData):
        f_token = "token"
        f_stream = "stream" # THE SOURCE PATH (CONDITIONALLY OPTIONAL)
        f_stream_source = "stream_source" # THE SOURCE PATH (CONDITIONALLY OPTIONAL)
        f_filename = "filename" # THE DESTINATION FILENAME        
        f_filepath = "filepath" # THE DESTINATION FILE PATH
        def get_defaults(self):
            return {
                self.f_stream: None, # Allow setting of None
            }
        def get_keys(self):
            return {
                self.f_token: str,
                self.f_stream: UploadService.DataReadable,
                self.f_stream_source: str,
                self.f_filename: str,
                self.f_filepath: str,
            }, {}
        
        def do_validation(self,key,value):
            #print(f"Validating  NewArgs- {key}:{value}")
            if key == self.f_filename:
                if not isinstance(value, str):
                    raise ValueError("filename must be a string")
                sep = os.path.sep
                alt = os.path.altsep or '/'
                if sep in value or alt in value:
                    raise ValueError(f"Invalid filename '{value}': must not contain path separators")

            if key == 'stream' and  value == None:
                #raise Exception("Cant have a null stream")
                value = None
            if key == 'stream' and  type(value) == str:
                value = io.BytesIO(value.encode('utf-8'))
            return value,""

        def do_get_filtered(self,key,value):
            if  key == 'filepath' and value == None:
                self[key] =  self[self.f_filepath]
                value =  self[key]
            if  key == 'stream' and value == None:
                #print(f" DYNAMIC: OPENING FILE STREAM : {self['stream_source']}")
                value =  open(self['stream_source'],"r")
                self[key] =  value
            return value

    class tHostAddress(BaseData):
        f_protocol = "protocol"
        f_port = "port"
        f_host = "host"        
        f_url = "url"        
        f_command_uri = "command_uri"        
        def get_keys(self):
            return {
                self.f_protocol: str,
                self.f_port: str,
                self.f_host: str,
                self.f_url: str,
                self.f_command_uri: str,
            }, {}
        
        def getUrl(self):
            URL = f"{self[self.f_protocol]}://{self[self.f_host]}:{self[self.f_port]}/{self[self.f_url]}"
            return URL
        
        def getCommandUrl(self):
            URL = f"{self[self.f_protocol]}://{self[self.f_host]}:{self[self.f_port]}/{self[self.f_command_uri]}"
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
        f_command_uri = "command_uri"
        def get_keys(self):
            required = {
                self.f_web_html_dir: str,
                self.f_tokens: str,
                self.f_upload_dir: str,
                self.f_command_uri: str
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
            "upload_directory": {
                "required_args": [],
                "method": cls._upload_directory,
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
    def ToDDBFolderInfo(cls,uploadRecord,hostSpec):
        # Pre Conversion
        r = cls.EntityID
        rec = cls.EntityID(uploadRecord)
        hostCtx = cls.tHostSpec(hostSpec)     
        
        # Do Convert
        eid = DDBFolder.EntityID({
            DDBFolder.EntityID.f_filename       : rec[rec.f_filename]})
        pathInfo = DDBFolder.WriteContext({
            DDBFolder.WriteContext.f_file_root  : hostCtx[hostCtx.f_upload_dir],
            DDBFolder.WriteContext.f_path       :  rec[rec.f_filepath]
            })
        # Post Conversion
        return eid, pathInfo
    
    @classmethod
    def _has_file_server(cls,recordInfo,hostSpec):
        eid,pathInfo =  cls.ToDDBFolderInfo (recordInfo,hostSpec)
        eid = DDBFolder.EntityID(eid)
        pathInfo = DDBFolder.WriteContext(pathInfo)
        val = DDBFolder.has_file(eid,pathInfo)
        assert val in [True, False]
        return val

    @classmethod
    def _upload_file(cls,**kwargs):
        s = cls.tHostAddress(kwargs)     
        d = cls.tClientUploadData(kwargs)
        stream = d[d.f_stream]
        with stream: #consume the stream and close it off.
            files = {"file": (d[d.f_filename], stream)}
            headers = {"Upload-Token": d[d.f_token]}
            data = {d.f_filepath: d[d.f_filepath]}  # Additional form field
            # See: _flask_server_upload_file next
            resp = requests.post(s.getUrl(), 
                                    headers=headers, 
                                    files=files,
                                    data=data)
            try:
                rec = DDBFolder.Record(json.loads(resp.text))
            except Exception as e:
                print(f"_upload_file  failed to parse Record: DDBFolder.Record({resp.text})")
                raise e
        return rec


    @classmethod
    def _map_directory(cls, client_data):
        """
        Recursively scan client_data[f_filepath] and return a dict:
          { index: {'data': tClientUploadData(kwargs), 'status':'unuploaded', 'size': bytes} }
        """
        base = client_data[client_data.f_stream_source]
        files = []
        for root, _, filenames in os.walk(base):
            for fn in filenames:
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, base)
                files.append((rel, path))
        mapped = {}
        for idx, (rel, full) in enumerate(sorted(files)):
            entry = dict(client_data)  # copy original dict
            entry[client_data.f_filepath] = os.path.join(client_data[client_data.f_filepath],client_data[client_data.f_filename] ,os.path.dirname(rel))
            entry[client_data.f_filename] =  os.path.basename(rel)
            entry[client_data.f_stream_source] = os.path.join(base,rel)
            entry[client_data.f_stream] = None
            ts = cls.tTransferProgress
            mapped[idx] = cls.tTransferProgress({
                ts.f_data: cls.tClientUploadData(entry),
                ts.f_status: 'unuploaded',
                ts.f_progress: 0,
                ts.f_size: os.path.getsize(full),
            })
        return mapped

    @classmethod
    def _remote_has_file(cls, **kwargs):
        s = cls.tHostAddress(kwargs['hostAddress'])     
        eid = cls.EntityID(kwargs['eid'])
        c = cls.Command
        cmd = cls.Command({
                c.f_command_id :"has_file",    
                c.f_executor_id :"anon",
                c.f_args :eid,
                c.f_data :{},
                c.f_auth :{}
        })
        
        #headers = {"Upload-Token": d[d.f_token]}
        headers = {}

        print("SENDING")
        print(json.dumps(cmd,indent =1))
        '''
        cmd = {
            "command_id": "has_file",
            "executor_id": "anon",
            "args": {
            "FILE_NOTE_IGNORE": "This is the required data for a test upload",
            "token": "aaaaaa",
            "filename": "file_0.txt",
            "filepath": "./upload_root/demo_folder/level0_0/level1_0",
            "stream_source": "./__client/demo_folder/level0_0/level1_0/file_0.txt",
            "stream": null,
            "ADDY_NOTE_IGNORE": "This file is given to a http client",
            "protocol": "http",
            "port": "5000",
            "host": "localhost",
            "url": "/do_upload",
            "has_file_uri": "/has_file"
            },
        "data": {},
        "auth": {}
        }        
        '''
        resp = requests.post(s.getCommandUrl(), 
                                headers={
                                    **headers, 
                                    "Content-Type":"application/json"}, 
                                data=json.dumps(cmd))
        try:
            dat = json.loads(resp.text)
        except:
            print(resp.text)
            raise Exception(f"Bad file response from server: {resp.text}")
        assert dat in [True,False]
        return dat

    @classmethod
    def _upload_directory(cls, **kwargs):

        folderSpec = cls.tClientUploadData(kwargs)
        ts = cls.tTransferProgress

        mapped = cls._map_directory(folderSpec)
        if len(mapped.keys()) == 0:
            raise Exception(f"I gots no keys from _map_directory {json.dumps(folderSpec,indent=4)}")
        results = {}
        for idx, transfer in mapped.items():
            transfer = cls.tTransferProgress(transfer)
            uploadRecord = cls.tClientUploadData(transfer[ts.f_data])
            uploadEID = cls.EntityID(transfer[ts.f_data])
            args = {
                        '__command':['upload_file'],
                        **cls.tHostAddress(kwargs),
                        **uploadRecord
                    }
            #client_filepath = transfer[ts.f_data][cls.tClientUploadData.f_filepath]
            rec = cls.run(** args)
            results[idx] = transfer.copy()
                        
            has_file = cls._remote_has_file( eid = cls.EntityID(uploadEID), hostAddress = cls.tHostAddress(kwargs))
            if type(has_file) == bool and has_file==True :
                results[idx][ts.f_progress] = 1
                results[idx][ts.f_status] = 'uploaded'
            else:
                results[idx][ts.f_progress] = 0
                results[idx][ts.f_status] = 'failed'
                #return results
            try:
                results[idx][td.f_stream].close()
            except:
                pass

        return results


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
        ddbFolderCtx = DDBFolder.WriteContext(            {
                'file_root': hostSpec[hostSpec.f_upload_dir],
                'path': client_filepath,
                'do_overwrite':True,
        })
        obj = DDBFolder.create_file(
            {
                #'owner_id': "12345",
                #'parent_id': "",
                #'name': f"test_file_{i}",
                'filename': f.filename,
                'stream': f,
            },ddbFolderCtx
        )
        # Validate that we have a valid record as a response
        obj = DDBFolder.Record(obj) 
        #cls.on_upload(save_path)
        return (json.dumps(obj), 201)        


    @classmethod
    def _cmd_start(cls, **kwargs):
        ha = cls.tHostSpec(kwargs)
        cmdDict = BaseService.flatten(kwargs)
        cmdArgs = BaseService.to_arg_string(cmdDict)
        #print(json.dumps(cmdDict,indent=4))
        jobs = Jobs()
        run_command = "python3 "+os.path.abspath(__file__)+" launch "+cmdArgs
        #print(run_command)
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
        #print("uploaded path "+pth)
        pass

    @classmethod
    def _cmd_launch(cls, **kwargs):
        ha = cls.tHostSpec(kwargs)

        root_dir = ha[ha.f_web_html_dir]
        upload_dir = ha[ha.f_upload_dir]
        command_uri = ha[ha.f_command_uri]
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
            try:
                full = os.path.join(os.getcwd(), root_dir, u_path.lstrip("/"))
                if os.path.isfile(full):
                    return send_from_directory(os.path.join(os.getcwd(), root_dir), u_path)
                return Response(f"File not found at: {full}", status=404)
            except Exception as e:
                import traceback as tb
                return (tb.format_exc(),500)
        
        @app.route(command_uri, methods=["POST"])
        def process_command():
            #return ("FAIL",500)
            try:

                #eid = cls.EntityID(kwargs['eid'])
                c = cls.Command
                #return str(request.get_json())
                cmd = cls.Command(request.get_json())
                if cmd[c.f_command_id] == "has_file":  
                    eid = cls.EntityID(cmd[c.f_args])
                    val = cls._has_file_server(eid,ha)
                    val = json.dumps(val)
                    return(val,201)                                  
                return json.dumps({"error":"command not found"})

            except:
                import traceback as tb
                return (tb.format_exc(),500)

        @app.route(upload_url, methods=["POST"])
        def upload():
            try:
                return cls._upload_file_p2(request,ha)
            except Exception as e:
                import traceback as tb
                return (tb.format_exc(),500)

        # Run Flask
        print(f"Starting upload server on {host}:{port}")
        app.run(host=host, port=port)
        return 0

    @classmethod
    def _cmd_test(cls, **kwargs):
        
        import importlib.util
        import unittest
        from io import StringIO

        # determine current module path and test filename
        service_path = os.path.abspath(__file__)
        test_path = service_path.replace('.py', '.tests.py')

        # load the test module dynamically
        spec = importlib.util.spec_from_file_location('service_tests', test_path)
        tests_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tests_mod)

        # run unittest on that module
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(tests_mod)
        stream = StringIO()
        runner = unittest.TextTestRunner(stream=stream, verbosity=2)
        result = runner.run(suite)

        # build JSON report
        report = {
            'testsRun': result.testsRun,
            'failures': [(str(tc), msg) for tc, msg in result.failures],
            'errors':   [(str(tc), msg) for tc, msg in result.errors],
            'skipped':  [(str(tc), msg) for tc, msg in getattr(result, 'skipped', [])],
            'wasSuccessful': result.wasSuccessful()
        }
        print(json.dumps(report,indent=4))
        return report

        

if __name__ == "__main__":
    #from dotenv import load_dotenv
    #load_dotenv()     
    #UploadService.run_cli()
    print(DDBFolder)
# python simple_upload_host.py launch ![server=./test_specs/hostSpec.json]!
# python simple_upload_host.py upload_file ![fileSpec=./test_specs/testUploadSpec.json]! ![serverAddy=./test_specs/hostAddress.json]!
# python simple_upload_host.py test fileSpec=![./test_specs/testUploadSpec.json]! hostAddress=![./test_specs/hostAddress.json]! hostSpec=![./test_specs/hostSpec.json]!
# python simple_upload_host.py test
