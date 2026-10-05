# contract=UploadService
# version=0.1
import sys
import os
import uuid
import tempfile, time, json
from flask import Flask, send_from_directory, Response, request, abort
from werkzeug.utils import secure_filename
from nodejobs.dependencies.BaseService import BaseService
from nodejobs.dependencies.BaseData import BaseData
from nodejobs.jobs import Jobs
import requests
from typing import Protocol, runtime_checkable, List, Any
try:
    from decelium_core_data.DDBFolder import DDBFolder
    from decelium_core_data.generic_entity import DataReadable
    _core_data_available = True
    _core_data_error = None
except Exception as e:
    DDBFolder = None
    _core_data_available = False
    _core_data_error = e

    class DataReadable:
        pass
import datetime
import typing
import psutil, inspect
from flask_cors import CORS
from werkzeug.datastructures import FileStorage

if _core_data_available:
    DataReadable.register(FileStorage)
else:
    class _DDBFolderProxy:
        def __getattr__(self, name):
            raise ImportError("decelium_core_data is required for simple_upload_host") from _core_data_error

    DDBFolder = _DDBFolderProxy()


class jsondateencode_local:
    @staticmethod
    def loads(dic):
        return json.loads(dic, object_hook=jsondateencode_local.datetime_parser)

    @staticmethod
    def dumps(dic, indent=0):
        return json.dumps(dic, default=jsondateencode_local.datedefault, indent=indent)

    @staticmethod
    def datedefault(o):
        if isinstance(o, tuple):
            l = ["__ref"]
            l = l + o
            return l
        if isinstance(
            o,
            (
                datetime.date,
                datetime.datetime,
            ),
            ):
                return o.isoformat()

    @staticmethod
    def datetime_parser(dct):
        DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
        for k, v in dct.items():
            if isinstance(v, str) and "T" in v:
                try:
                    dct[k] = datetime.datetime.strptime(v, DATE_FORMAT)
                except:
                    pass
        return dct


class UploadService(BaseService):
    class tTransferProgress(BaseData):
        f_size = "size"
        f_progress = "progress"
        f_status = "status"
        f_data = "data"
        f_attrib = "attrib"

        def get_keys(self):
            required = {
                self.f_status: str,
                self.f_size: int,
                self.f_progress: int,
                self.f_data: dict,
                self.f_attrib: dict,
            }
            optional = {}
            return required, optional

    class Command(BaseData):
        f_command_id = "command_id"
        f_executor_id = "executor_id"
        f_args = "args"
        f_data = "data"
        f_auth = "auth"

        def __init__(
            self,
            in_dict=None,
            trim=False,
            *,
            command_id=None,
            executor_id="anon",
            args=None,
            data=None,
            auth=None,
        ):
            d = (in_dict or {}).copy()

            def override(key, value, default=None):
                if value is not None:
                    d[key] = value
                elif key not in d and default is not None:
                    d[key] = default

            override(self.f_command_id, command_id)
            override(self.f_executor_id, executor_id, "anon")
            override(self.f_args, args, {})
            override(self.f_data, data, {})
            override(self.f_auth, auth, {})

            super().__init__(d, trim=trim)

        @classmethod
        def Blank(cls, eid):
            return {
                cls.f_command_id: "BLANK_COMMAND",
                cls.f_executor_id: "anon",
                cls.f_args: UploadService.EntityID(eid),
                cls.f_data: {},
                cls.f_auth: {},
            }

        def get_keys(self):
            return {
                self.f_command_id: str,
                self.f_executor_id: str,
                self.f_args: dict,
                self.f_data: dict,
                self.f_auth: dict,
            }, {}

    class EntityID(BaseData):
        def __init__(self, in_dict=None, trim=False, *, filename=None, filepath=None):
            # allow kwarg shorthand
            if filename is not None or filepath is not None:
                in_dict = {self.f_filename: filename, self.f_filepath: filepath}
            super().__init__(in_dict or {}, trim)

        f_filename = "filename"  # THE DESTINATION FILENAME
        f_filepath = "filepath"  # THE DESTINATION FILE PATH

        def get_keys(self):
            return {
                self.f_filename: str,
                self.f_filepath: str,
            }, {}

    class tResponse(BaseData):
        f_nonce = "nonce"
        f_value = "value"
        f_error = "error"
        f_attrib = "attrib"

        def __init__(
            self,
            in_dict=None,
            trim=False,
            *,
            nonce=None,
            value=None,
            error=None,
            attrib=None,
        ):
            d = (in_dict or {}).copy()

            def override(key, value, default=None):
                if value is not None:
                    d[key] = value
                elif key not in d and default is not None:
                    d[key] = default

            override(self.f_nonce, nonce, f"{uuid.uuid4().hex}")
            override(self.f_value, value, None)
            override(self.f_error, error, None)
            override(self.f_attrib, attrib, {})

            super().__init__(d, trim=trim)

        def get_keys(self):
            return {
                self.f_nonce: str,
                self.f_value: Any,
                self.f_error: Any,
                self.f_attrib: dict,
            }, {}

    class tClientUploadData(BaseData):
        f_token = "token"
        f_stream = "stream"  # THE SOURCE PATH (CONDITIONALLY OPTIONAL)
        f_stream_source = "stream_source"  # THE SOURCE PATH (CONDITIONALLY OPTIONAL)
        f_filename = "filename"  # THE DESTINATION FILENAME
        f_filepath = "filepath"  # THE DESTINATION FILE PATH
        f_attrib = "attrib"  # THE DESTINATION FILE PATH
        f_do_overwrite = "do_overwrite"  # THE DESTINATION FILE PATH

        def get_defaults(self):
            return {
                self.f_stream: None,  # Allow setting of None
            }

        def get_keys(self):
            return {
                self.f_token: str,
                self.f_stream: DataReadable,
                self.f_stream_source: str,
                self.f_filename: str,
                self.f_attrib: dict,
                self.f_filepath: str,
            }, {
                self.f_do_overwrite: bool,
            }

        def do_validation(self, key, value):
            # print(f"Validating  NewArgs- {key}:{value}")

            if key == self.f_filename:
                if not isinstance(value, str):
                    raise ValueError("filename must be a string")
                sep = os.path.sep
                alt = os.path.altsep or "/"
                if sep in value or alt in value:
                    raise ValueError(
                        f"Invalid filename '{value}': must not contain path separators"
                    )

            if key == "stream" and value == None:
                # raise Exception("Cant have a null stream")
                value = None
            if key == "stream" and type(value) == str:
                value = io.BytesIO(value.encode("utf-8"))
            return value, ""

        def do_get_filtered(self, key, value):
            if key == "filepath" and value == None:
                self[key] = self[self.f_filepath]
                value = self[key]
            if key == "stream" and value == None:
                # print(f" DYNAMIC: OPENING FILE STREAM : {self['stream_source']}")
                value = open(self["stream_source"], "rb")
                self[key] = value
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

    class tPublishedSite(BaseData):
        f_domain = "domain"
        f_eid = "entity_id"

        def get_keys(self):
            required = {
                self.f_domain: str,
                self.f_eid: UploadService.EntityID,
            }
            return required, {}

    class tHostSpec(tHostAddress):
        # likely from tHostAddress (fyi)
        # f_protocol = "protocol"
        # f_port = "port"
        # f_host = "host"
        # f_url = "url"
        f_upload_dir = "upload_dir"
        f_settings_dir = "settings_dir"
        f_tokens = "tokens"
        f_command_uri = "command_uri"
        f_published = "published"
        f_open_ai_key = "open_ai_key"
        f_do_overwrite = "do_overwrite"
        f_cwd = "cwd"

        def get_keys(self):
            required = {
                self.f_tokens: str,
                self.f_upload_dir: str,
                self.f_settings_dir: str,
                self.f_command_uri: str,
            }
            ha_required, _ = super().get_keys()
            # Now update 'required' in-place.
            required.update(ha_required)
            return required, {
                self.f_published: list,  # TESTtyping.List[UploadService.tPublishedSite],
                self.f_open_ai_key: str,
                self.f_do_overwrite: bool,
                self.f_cwd: str,
            }

        def do_pre_process(self, in_dict):
            if self.f_published not in in_dict:
                in_dict[self.f_published] = []
            return super().do_pre_process(in_dict)

        def do_validation(self, key, value):
            # validate site_roots is a list of published‐site specs
            if key == self.f_published:
                if not isinstance(value, list):
                    raise TypeError(f"{self.f_published}:{value} must be a list")
                validated = []
                for entry in value:
                    # will raise if entry is invalid
                    published = UploadService.tPublishedSite(entry)
                    validated.append(published)
                return validated, ""
            # fall back to parent
            return super().do_validation(key, value)

    """
    Idea
    @classmethod
    def get_command_map_NEW(cls):
        return {
            name.removeprefix("_cmd_"): {
                "required_args": [],
                "method": getattr(cls, name)
            }
            for name in dir(cls)
            if callable(getattr(cls, name)) and name.startswith("_cmd_")
        }        
    # IDE ENHANCEMENT
    @classmethod 
    def launch(cls,**kwargs):   
        return  cls.run(**{'__command':'launch', ** kwargs})
    @classmethod 
    def logs(cls,**kwargs):  
        return  cls.run(**{'__command':'launch', ** kwargs})
    ... many ... 
    """

    @classmethod
    def get_command_map(cls):
        return {
            "launch": {
                "required_args": [],
                "method": cls._cmd_launch,
            },
            "testcmd": {
                "required_args": [],
                "method": cls._cmd_testcmd,
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
            "add_published": {
                "required_args": [],
                "method": cls._cmd_add_published,
            },
            "list_published": {
                "required_args": [],
                "method": cls._cmd_list_published,
            },
            "delete_published": {
                "required_args": [],
                "method": cls._cmd_delete_published,
            },
        }

    @classmethod
    def ToDDBFolderInfo(cls, uploadRecord, hostSpec):
        # Pre Conversion
        r = cls.EntityID
        rec = cls.EntityID(uploadRecord)
        hostCtx = cls.tHostSpec(hostSpec)

        # Do Convert
        eid = DDBFolder.EntityID({DDBFolder.EntityID.f_filename: rec[rec.f_filename]})
        pathInfo = DDBFolder.WriteContext(
            {
                DDBFolder.WriteContext.f_file_root: hostCtx[hostCtx.f_upload_dir],
                DDBFolder.WriteContext.f_path: rec[rec.f_filepath],
            }
        )
        # Post Conversion
        return eid, pathInfo

    @classmethod
    def _has_file_server(cls, recordInfo, hostSpec):
        eid, pathInfo = cls.ToDDBFolderInfo(recordInfo, hostSpec)
        eid = DDBFolder.EntityID(eid)
        pathInfo = DDBFolder.WriteContext(pathInfo)
        val = DDBFolder.has_file(eid, pathInfo)
        assert val in [True, False]
        return val

    @classmethod
    def _determine_root_dir(cls, host_spec: dict) -> str:
        """
        a) Validate and extract the list of published sites from host_spec.
        b) Match request.host against those domains.
        c) Fallback to a 'localhost' entry if no exact match.
        d) Return the corresponding root directory (entity_id.filepath).
        """
        spec = cls.tHostSpec(host_spec)
        published = spec[spec.f_published]  # list of raw dicts

        # normalize incoming host (strip port)
        host_header = request.host.split(":", 1)[0]

        # helper to pull filepath from a tPublishedSite
        def filepath_from(site_dict):
            pub = UploadService.tPublishedSite(site_dict)

            eid = cls.EntityID(pub[pub.f_eid])
            return os.path.join(eid[eid.f_filename])

        debuggingDat = [str(len(published))]
        # 1. exact match
        for site_dict in published:
            domain = cls.tPublishedSite(site_dict)[cls.tPublishedSite.f_domain]
            debuggingDat.append(f"{domain}:{host_header}")
            if domain == host_header:
                debuggingDat.append(f"SELECTED {domain}:{host_header}")
                # return debuggingDat
                return filepath_from(site_dict)

        # !!!If you are having problems you can return the domain serarch data here.
        # return debuggingDat

        # 2. fallback to localhost
        # for site_dict in published:
        #    if cls.tPublishedSite(site_dict)[cls.tPublishedSite.f_domain] in ("localhost", "127.0.0.1"):
        #        return filepath_from(site_dict)

        # 3. no match → error
        return "/error/path/fhldja/fndl/fbja"  # Trigger a Not found error downstream. The only hack so far!

    @classmethod
    def _upload_file(cls, **kwargs):
        s = cls.tHostAddress(kwargs)
        d = cls.tClientUploadData(kwargs)
        stream = d[d.f_stream]
        with stream:  # consume the stream and close it off.
            files = {"file": (d[d.f_filename], stream)}
            headers = {"Upload-Token": d[d.f_token]}
            data = {d.f_filepath: d[d.f_filepath]}  # Additional form field
            # See: _flask_server_upload_file next
            try:
                resp = requests.post(
                    s.getUrl(), headers=headers, files=files, data=data
                )
                try:
                    rec = DDBFolder.Record(jsondateencode_local.loads(resp.text))
                except Exception as e:
                    return cls.tResponse(
                        value=False,
                        error="Server could not process recordCant process record "
                        + resp.text,
                        attrib={},
                    )
            except Exception as e:
                import traceback as tb

                errstr = tb.format_exc()
                return cls.tResponse(
                    value=False,
                    error="Cant Connect to server URL could not process recordCant process record "
                    + s.getUrl()
                    + f":\n {errstr} ",
                    attrib={},
                )

        return cls.tResponse(value=rec, error=None, attrib={})

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
            entry[client_data.f_filepath] = os.path.join(
                client_data[client_data.f_filepath],
                client_data[client_data.f_filename],
                os.path.dirname(rel),
            )
            entry[client_data.f_filename] = os.path.basename(rel)
            entry[client_data.f_stream_source] = os.path.join(base, rel)
            entry[client_data.f_stream] = None
            ts = cls.tTransferProgress
            mapped[idx] = cls.tTransferProgress(
                {
                    ts.f_data: cls.tClientUploadData(entry),
                    ts.f_attrib: {},
                    ts.f_status: "unuploaded",
                    ts.f_progress: 0,
                    ts.f_size: os.path.getsize(full),
                }
            )
        return mapped

    @staticmethod
    def _format_size_compact(num_bytes) -> str:
        try:
            size = float(num_bytes or 0)
        except Exception:
            size = 0.0
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while size >= 1024.0 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    @classmethod
    def run_remote(cls, hostAddress, cmd):
        headers = {}
        s = UploadService.tHostAddress(hostAddress)

        resp = requests.post(
            s.getCommandUrl(),
            headers={**headers, "Content-Type": "application/json"},
            data=jsondateencode_local.dumps(cmd),
        )
        try:
            dat = jsondateencode_local.loads(resp.text)
        except:
            print(resp.text)
            raise Exception(f"Bad file response from server: {resp.text}")
            dat = None
        # assert dat in [True,False]
        return dat

    @classmethod
    def _upload_directory(cls, **kewargs):
        folderSpec = cls.tClientUploadData(kewargs["folderData"])
        ha = UploadService.tHostAddress(kewargs["hostAddress"])
        ts = cls.tTransferProgress

        mapped: List[UploadService.tTransferProgress] = cls._map_directory(folderSpec)
        if len(mapped.keys()) == 0:
            raise Exception(
                f"I gots no keys from _map_directory {jsondateencode_local.dumps(folderSpec, indent=4)}"
            )
        results = {}
        for idx, transfer in mapped.items():
            transfer = cls.tTransferProgress(transfer)
            uploadRecord = cls.tClientUploadData(transfer[ts.f_data])
            try:
                source_path = str(uploadRecord[uploadRecord.f_stream_source])
            except Exception:
                source_path = ""
            try:
                size_bytes = int(transfer[ts.f_size])
            except Exception:
                size_bytes = 0
            size_text = cls._format_size_compact(size_bytes)
            print(f'uploading ({size_text}) "{source_path}" ...', flush=True)
            uploadEID = cls.EntityID(transfer[ts.f_data])
            args = {
                "__command": ["upload_file"],
                **cls.tHostAddress(ha),
                **uploadRecord,
            }
            # client_filepath = transfer[ts.f_data][cls.tClientUploadData.f_filepath]
            rec = cls.run(**args)
            results[idx] = transfer.copy()
            c = UploadService.Command

            # has_file = cls.run_remote( hostAddress = ha, cmd={  c.f_command_id :"has_file", **UploadService.Command.Blank(uploadEID)})
            has_file = UploadService.run_remote(
                hostAddress=ha,
                cmd=UploadService.Command(
                    command_id="has_file", args=UploadService.EntityID(uploadEID)
                ),
            )
            if type(has_file) == bool and has_file == True:
                results[idx][ts.f_progress] = 1
                results[idx][ts.f_status] = "uploaded"
                results[idx][ts.f_attrib]["resp.upload_file"] = str(rec)
                results[idx][ts.f_attrib]["resp.has_file"] = str(has_file)
                print("... upload finished", flush=True)
            else:
                results[idx][ts.f_progress] = 0
                results[idx][ts.f_status] = "failed"
                results[idx][ts.f_attrib]["resp.upload_file"] = str(rec)
                results[idx][ts.f_attrib]["resp.has_file"] = str(has_file)
                # return results
                print("... upload failed", flush=True)
            try:
                results[idx][td.f_stream].close()
            except:
                pass

        return results

    @classmethod
    def _upload_file_p2(cls, request, hostSpec: dict):
        hostSpec = cls.tHostSpec(hostSpec)
        token = request.headers.get("Upload-Token")
        if token not in hostSpec[hostSpec.f_tokens]:
            abort(
                401,
                f"Invalid or missing Upload-Token: {token} for {hostSpec[hostSpec.f_tokens]}",
            )

        if "file" not in request.files:
            abort(400, "Missing file part")

        f = request.files["file"]
        if f.filename == "":
            abort(400, "Empty filename")
        client_filepath = request.form.get(cls.tClientUploadData.f_filepath)
        filename = f"{uuid.uuid4().hex}.dat"
        # os.makedirs(hostSpec[hostSpec.f_upload_dir], exist_ok=True)

        # save_path = os.path.join(hostSpec[hostSpec.f_upload_dir],filename)
        # f.save(save_path)
        ddbFolderCtx = DDBFolder.WriteContext(
            {
                "file_root": hostSpec[hostSpec.f_upload_dir],
                "path": client_filepath,
                "do_overwrite": True,
            }
        )

        obj = DDBFolder.create_file(
            {
                #'owner_id': "12345",
                #'parent_id': "",
                #'name': f"test_file_{i}",
                "filename": f.filename,
                "stream": f,
            },
            ddbFolderCtx,
        )
        # Validate that we have a valid record as a response
        obj = DDBFolder.Record(obj)
        # cls.on_upload(save_path)
        return (jsondateencode_local.dumps(obj), 201)

    @classmethod
    def MakeJobs(cls, ha):
        ha = cls.tHostSpec(ha)
        cwd = ha[ha.f_cwd] if ha.f_cwd in ha else None
        if cwd and not os.path.isabs(cwd):
            cwd = os.path.abspath(os.path.join(os.getcwd(), cwd))
        if cwd and not os.path.isdir(cwd):
            raise Exception(f"cwd does not exist: {cwd}")
        base_dir = cwd or os.getcwd()
        settings_dir = ha[ha.f_settings_dir]
        if not os.path.isabs(settings_dir):
            settings_dir = os.path.join(base_dir, settings_dir)
        jobs = Jobs(settings_dir + "/jobs")
        return jobs

    @classmethod
    def _cmd_start(cls, **kwargs):
        ha = cls.tHostSpec(kwargs)
        cmdDict = BaseService.flatten(kwargs)
        cmdArgs = BaseService.to_arg_string(cmdDict)
        jobs = cls.MakeJobs(ha)
        print(f"_cmd_start kwargs: {kwargs}")
        print(f"\n\n")
        print(f"_cmd_start cmdDict: {cmdDict}")
        print(f"\n\n")
        print(f"_cmd_start cmdArgs: {cmdArgs}")
        print(f"\n\n")
        module = sys.modules[cls.__module__]
        candidate = getattr(module, "__file__", None)
        # or more robustly:
        source = inspect.getsourcefile(cls) or candidate
        script = os.path.abspath(source)

        run_command = [
            sys.executable,
            script,
            "launch",
            *[f"{k}={v}" for k, v in cmdDict.items()],
        ]
        print(f"_cmd_start run_command 2: {run_command}")
        print(f"\n\n")
        cwd = ha[ha.f_cwd] if ha.f_cwd in ha else None
        if cwd and not os.path.isabs(cwd):
            cwd = os.path.abspath(os.path.join(os.getcwd(), cwd))
        if cwd and not os.path.isdir(cwd):
            raise Exception(f"cwd does not exist: {cwd}")
        if not cwd:
            cwd = os.getcwd()
        result = jobs.run(command=run_command, job_id="http_upload", cwd=cwd)
        return jobs.list_status({"dirname": "http_upload"})

    @classmethod
    def _cmd_list(cls, **kwargs):
        jobs = cls.MakeJobs(kwargs)
        return jsondateencode_local.dumps(
            dict(jobs.list_status({"dirname": "http_upload"}))
        )

    @classmethod
    def _cmd_logs(cls, **kwargs):
        jobs = cls.MakeJobs(kwargs)
        return jobs.job_logs(job_id="http_upload")

    @classmethod
    def _cmd_stop(cls, **kwargs):
        jobs = cls.MakeJobs(kwargs)

        result = jobs.stop(job_id="http_upload")
        return jobs.list_status({"dirname": "http_upload"})

    @classmethod
    def on_upload(cls, pth):
        # print("uploaded path "+pth)
        pass

    @classmethod
    def _cmd_testcmd(cls, **kwargs):
        print("TEST")

    @classmethod
    def _init_thenload(cls, ha, do_overwrite=False):
        # 1 - Create Default file info
        tRec = DDBFolder.Record
        ha = UploadService.tHostSpec(ha)
        currentFile: DDBFolder.Record = DDBFolder.Record(
            **{
                "filename": "server_settings",
            }
        )
        strData = jsondateencode_local.dumps(ha)
        # haEid:DDBFolder.Record = tRec(currentFile)
        settingsCtx = DDBFolder.WriteContext(
            {
                "file_root": ha[ha.f_settings_dir],
                "path": "./",
                "do_overwrite": do_overwrite,
            }
        )

        # print("Dir Record")
        # print(json.dumps(newFolder,indent=3))
        # return None
        cls._create_file_ifnexist(
            currentRecord=tRec(
                **{"is_folder": True}
            ),  # Create a folder in the root here, by not specifying a name or path
            strData="",
            locationCtx=settingsCtx,
            do_overwrite=False,
        )

        fileRec = tRec(
            cls._create_file_ifnexist(
                currentRecord=currentFile,
                strData=strData,
                locationCtx=settingsCtx,
                do_overwrite=do_overwrite,
            )
        )
        with DDBFolder.open_payload(fileRec, settingsCtx, "r") as f:
            strData = f.read()
        storedRec = jsondateencode_local.loads(strData)
        return storedRec

    @classmethod
    def _create_file_ifnexist(
        cls, currentRecord, strData: str, locationCtx, do_overwrite=False
    ):
        # 2 - If we are forcing overwrite, remove old file
        fileEid: DDBFolder.Record = DDBFolder.Record(currentRecord)
        if do_overwrite == True and DDBFolder.has_file(fileEid, locationCtx) == True:
            DDBFolder.delete_file(fileEid, locationCtx)

        # 2 - Either way, now we return the disk, or a new settings file
        if DDBFolder.has_file(fileEid, locationCtx) == True:
            fileRec: DDBFolder.Record = DDBFolder.Record(
                DDBFolder.load_object(fileEid, locationCtx)
            )
            if fileRec[fileRec.f_is_folder] == False:
                with DDBFolder.open_payload(fileEid, locationCtx, "r") as f:
                    strData = f.read()
                strData = strData
            else:
                strData = ""  # We are dealing with a folder
        else:
            if currentRecord[DDBFolder.Record.f_is_folder] == False:
                fileRec: DDBFolder.Record = DDBFolder.create_file(
                    DDBFolder.NewArgs({"stream": strData, **currentRecord}), locationCtx
                )
            else:
                # crn = DDBFolder.NewArgs(currentRecord)
                # print(jsondateencode_local.dumps(crn,indent=4))
                fileRec: DDBFolder.Record = DDBFolder.create_file(
                    DDBFolder.NewArgs(currentRecord), locationCtx
                )
        return fileRec

    @classmethod
    def _cmd_add_published(cls, hostSpec: dict, siteSpec: dict):
        new_site = cls.tPublishedSite(siteSpec)
        ha = cls._init_thenload(hostSpec, do_overwrite=False)
        ha = cls.tHostSpec(ha)
        # If you already have an entry, fail
        for existing in ha[ha.f_published]:
            existing_site = cls.tPublishedSite(existing)
            if existing_site[existing_site.f_domain] == new_site[new_site.f_domain]:
                return False

        ha[ha.f_published].append(new_site)
        ha = cls._init_thenload(ha, do_overwrite=True)
        # Verify Now:
        ha = cls._init_thenload(hostSpec, do_overwrite=False)
        ha = cls.tHostSpec(ha)
        # make sure list contains new site
        for existing in ha[ha.f_published]:
            existing_site = cls.tPublishedSite(existing)
            if existing_site[existing_site.f_domain] == new_site[new_site.f_domain]:
                return True

        return False

    @classmethod
    def _cmd_list_published(cls, hostSpec: dict, **kwargs) -> list:
        hostSpec = cls._init_thenload(hostSpec, do_overwrite=False)
        ha = cls.tHostSpec(hostSpec)
        return ha[ha.f_published]

    @classmethod
    def _cmd_delete_published(cls, hostSpec: dict, siteSpec: dict):
        hostSpec = cls._init_thenload(hostSpec, do_overwrite=False)
        ha = cls.tHostSpec(hostSpec)
        # filter out any matching domain
        assert "domain" in siteSpec
        domain = siteSpec["domain"]
        ha[ha.f_published] = [
            site for site in ha[ha.f_published] if site[site.f_domain] != domain
        ]
        ha = cls._init_thenload(ha, do_overwrite=True)
        ha = cls._init_thenload(ha, do_overwrite=False)
        ha = cls.tHostSpec(ha)
        for site in ha[ha.f_published]:
            if site[site.f_domain] == domain:
                return False
        return True

    @classmethod
    def _cmd_delete_directory(cls, eid: dict, hostAddress: dict):
        raise ("PSEUDO CODE ONLY")
        ha = cls.tHostAddress(hostAddress)
        dir_id = cls.EntityID(eid)

        # 1) load the folder record
        load_cmd = cls.Command(command_id="load_object", args=dict(dir_id))
        try:
            folder = cls.run_remote(hostAddress=dict(ha), cmd=dict(load_cmd))
        except Exception as err:
            return err

        if not isinstance(folder, dict) or "children_ids" not in folder:
            return ValueError(f"Bad load_object response: {folder}")

        # 2) delete each child by its self_id
        for child_self_id in folder["children_ids"].keys():
            del_child = cls.Command(
                command_id="delete_object", args={"self_id": child_self_id}
            )
            try:
                result = cls.run_remote(hostAddress=dict(ha), cmd=dict(del_child))
            except Exception as err:
                return err
            if result is not True:
                return ValueError(f"Failed deleting child {child_self_id}: {result}")

        # 3) delete the directory itself
        del_dir = cls.Command(command_id="delete_object", args=dict(dir_id))
        try:
            return cls.run_remote(hostAddress=dict(ha), cmd=dict(del_dir))
        except Exception as err:
            return err

    @classmethod
    def _after_launch_endpoints(cls, app, hostSpec):
        hostSpec = cls.tHostSpec(hostSpec)
        print("BASE LAUNCH")
        pass

    @classmethod
    def _cmd_launch(cls, **kwargs):
        print(f"Starting upload server ...")
        # **** TEMPLATE SETTINGS LOADED HERE
        print(json.dumps(kwargs, indent=2))
        cls.currentHa = cls.tHostSpec(kwargs)
        cwd = (
            cls.currentHa[cls.currentHa.f_cwd]
            if cls.currentHa.f_cwd in cls.currentHa
            else None
        )
        if cwd and not os.path.isabs(cwd):
            cwd = os.path.abspath(os.path.join(os.getcwd(), cwd))
        if cwd and not os.path.isdir(cwd):
            raise Exception(f"cwd does not exist: {cwd}")
        if cwd:
            os.chdir(cwd)
        cls._kill_conflicting_process(cls.currentHa)
        os.makedirs(cls.currentHa[cls.currentHa.f_upload_dir], exist_ok=True)
        os.makedirs(cls.currentHa[cls.currentHa.f_settings_dir], exist_ok=True)
        # **** SAVED SETTINGS LOADED HERE
        # do_overwrite = cls.currentHa ['do_overwrite']
        do_overwrite = False
        cls.currentHa: UploadService.tHostSpec = UploadService.tHostSpec(
            cls._init_thenload(cls.currentHa, do_overwrite=do_overwrite)
        )

        rootDDBRecord = DDBFolder.Record(
            cls._create_file_ifnexist(
                currentRecord=DDBFolder.Record(is_folder=True),
                strData=None,
                locationCtx=DDBFolder.WriteContext(
                    {
                        "file_root": cls.currentHa[cls.currentHa.f_upload_dir],
                        "path": "./",
                        "do_overwrite": False,
                    }
                ),
            )
        )

        # Build Flask app
        app = Flask(__name__, static_folder=None, static_url_path=None)
        app.config.from_object(__name__)
        CORS(app, resources={r"/*": {"origins": "*"}})

        # command_uri = ha[ha.f_command_uri]
        # port = ha[ha.f_port]
        # host = ha[ha.f_host]
        # tokens = ha[ha.f_tokens]
        # upload_dir = ha[ha.f_upload_dir]
        # upload_url = ha[ha.f_url]
        # Convert args
        # port = int(port)
        # VALID_TOKENS = set(ha[ha.f_tokens].split(","))

        @app.route("/", methods=["GET", "POST"])
        @app.route("/<path:u_path>", methods=["GET", "POST"])
        def index(u_path="/"):
            # return {"path":u_path},200
            # return cls._determine_root_dir(ha)
            try:
                root_dir = os.path.join(
                    os.getcwd(),
                    cls.currentHa[cls.currentHa.f_upload_dir],
                    cls._determine_root_dir(cls.currentHa),
                )

                rel_path = u_path.lstrip("/")
                full = os.path.join(root_dir, rel_path)

                if os.path.isfile(full):
                    return send_from_directory(root_dir, rel_path)
                if os.path.isdir(full):
                    index_path = os.path.join(full, "index.html")
                    if os.path.isfile(index_path):
                        return send_from_directory(full, "index.html")

                # return Response(f"File not found at: {full}", status=404)
                # return Response(f"Missing file at  {full}:{root_dir}:{rel_path}", status=200)
                try:
                    return send_from_directory(root_dir, "index.html")
                except Exception as e:
                    import traceback as tb

                    return (f"Error reading from {root_dir}--->" + tb.format_exc(), 500)
            except Exception as e:
                import traceback as tb

                return (tb.format_exc(), 500)

        @app.route(cls.currentHa[cls.currentHa.f_command_uri], methods=["POST"])
        def process_command():
            # return ("FAIL",500)
            try:
                # eid = cls.EntityID(kwargs['eid'])
                c = cls.Command
                # return str(request.get_json())
                cmd = cls.Command(request.get_json())
                if cmd[c.f_command_id] == "has_file":
                    eid = cls.EntityID(cmd[c.f_args])
                    val = cls._has_file_server(eid, cls.currentHa)
                    val = jsondateencode_local.dumps(val)
                    return (val, 201)

                if cmd[c.f_command_id] in [
                    "add_published",
                    "list_published",
                    "delete_published",
                ]:
                    # cmd.f_data must be a dict matching tPublishedSite schema
                    resp = cls.run(
                        **{
                            "__command": [cmd[c.f_command_id]],
                            "hostSpec": cls.currentHa,
                            **dict(cmd[c.f_data]),
                        }
                    )
                    cls.currentHa = UploadService.tHostSpec(
                        cls._init_thenload(cls.currentHa, do_overwrite=False)
                    )

                    return (jsondateencode_local.dumps(resp), 201)

                return jsondateencode_local.dumps(
                    {"error": f"command '{cmd[c.f_command_id]}' not found"}
                )

            except:
                import traceback as tb

                return (f"REQUEST {request.get_json()} ERROR " + tb.format_exc(), 500)

        @app.route(cls.currentHa[cls.currentHa.f_url], methods=["POST"])
        def upload():
            try:
                return cls._upload_file_p2(request, cls.currentHa)
            except Exception as e:
                import traceback as tb

                return (tb.format_exc(), 500)

        print("after launch")
        cls._after_launch_endpoints(app, cls.currentHa)
        print("finished")
        # sys.exit(0)
        # Run Flask
        print(
            f"Starting upload server on {cls.currentHa[cls.currentHa.f_host]}:{cls.currentHa[cls.currentHa.f_port]}"
        )
        try:
            app.run(
                host=cls.currentHa[cls.currentHa.f_host],
                port=int(cls.currentHa[cls.currentHa.f_port]),
            )
        except Exception as e:
            import traceback as tb

            print(tb.format_exc())
        return "ok"

    @classmethod
    def _kill_conflicting_process(cls, currentHa):
        """
        Kill any other process whose command-line contains both
        'port=<our port>' and 'simple_upload_host.py'.
        """
        port = currentHa[currentHa.f_port]
        my_pid = os.getpid()

        for proc in psutil.process_iter(["pid", "cmdline"]):
            if proc.pid == my_pid:
                continue
            try:
                cmdline = proc.info["cmdline"] or []
                if any(arg.startswith(f"port={port}") for arg in cmdline) and any(
                    "simple_upload_host.py" in arg for arg in cmdline
                ):
                    proc.terminate()
                    proc.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    @classmethod
    def _cmd_test(cls, **kwargs):
        import importlib.util
        import unittest
        from io import StringIO

        # determine current module path and test filename
        service_path = os.path.abspath(__file__)
        test_path = service_path.replace(".py", ".tests.py")

        # load the test module dynamically
        spec = importlib.util.spec_from_file_location("service_tests", test_path)
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
            "testsRun": result.testsRun,
            "failures": [(str(tc), msg) for tc, msg in result.failures],
            "errors": [(str(tc), msg) for tc, msg in result.errors],
            "skipped": [(str(tc), msg) for tc, msg in getattr(result, "skipped", [])],
            "wasSuccessful": result.wasSuccessful(),
        }
        print(jsondateencode_local.dumps(report, indent=4))
        return report


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    UploadService.run_cli()
    # print(DDBFolder)
# python simple_upload_host.py launch '[[server=./test_specs/hostSpec.json]]'
# python simple_upload_host.py start '[[server=./test_specs/hostSpec.json]]'
# python simple_upload_host.py upload_file '[[fileSpec=./test_specs/testUploadSpec.json]]' '[[serverAddy=./test_specs/hostAddress.json]]'
# python simple_upload_host.py test fileSpec=[[./test_specs/testUploadSpec.json]] hostAddress=[[./test_specs/hostAddress.json]] hostSpec=[[./test_specs/hostSpec.json]]
# python simple_upload_host.py test
# curl -H "Host: justingirard.com" http://localhost:5123/
