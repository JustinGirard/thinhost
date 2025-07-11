#!/usr/bin/env python3
import unittest
import os
import time
import shutil
import json
from dotenv import load_dotenv
from decelium_core_data.DDBFolder import DDBFolder
import requests
load_dotenv()

try:
    from simple_upload_host import UploadService
except:
    from .simple_upload_host import UploadService

from decelium_core_data.DDBFolder import DDBFolder

class TestUploadService(unittest.TestCase):
    def setUp(self):
        """
        Create a temporary test upload directory and define specs for host and file.
        """
        # Create a temporary upload directory for testing.
        self.server_root = './__server'
        self.client_root = './__client'
        self.server_upload_test_root = './temp_site/'
        #shutil.rmtree(self.server_root, ignore_errors=True)
        #shutil.rmtree(self.client_root, ignore_errors=True)

        # Host specification used by UploadService.tHostSpec and tHostAddress
        self.hostSpec = UploadService.tHostSpec({
            "HOST_NOTE_IGNORE":"This file is secret on the server",
            "upload_dir":f"{self.server_root}/data/sites",
            "settings_dir":f"{self.server_root}/data/settings",
            "published":[
                {'domain':'localhost',
                 'entity_id':{
                            'filename':self.server_upload_test_root,
                            'filepath':'',
                            }
                }
            ],
            "url":"/do_upload",
            "command_uri":"/cmd",
            "port":"5122",
            "host":"0.0.0.0",
            "protocol":"http",
            "tokens":"<<DSH_SERVER_TOKEN_LIST>>"
        })

        self.hostAddress = {
            "ADDY_NOTE_IGNORE":"This file is given to a http client",
            "protocol": "http",
            "port": "5122",
            "host": "localhost",
            "url": "/do_upload",
            "command_uri": "/cmd"
        }
        # File specification used by UploadService.tClientUploadData.
        self.baseFileSpec = UploadService.tClientUploadData({
            "FILE_NOTE_IGNORE":"This is the required data for a test upload",    
            "token": "<<DSH_CLIENT_TOKEN>>",
            "filename": "demo_file_2.txt",
            "attrib":{},
            "filepath": self.server_upload_test_root,
            "stream_source": f"{self.client_root}/demo_file_2.txt", # We can use stream source to lazy define the stream data, or store references.
            "stream": None,
            "do_overwrite":True
        })
        self.baseFolderSpec = UploadService.tClientUploadData({
            "FILE_NOTE_IGNORE":"This is the required data for a test upload",    
            "token": "<<DSH_CLIENT_TOKEN>>",
            "filename": "demo_folder",
            "attrib":{},
            "filepath":  self.server_upload_test_root, 
            "stream_source": f"{self.client_root}/demo_folder", ## USUALLY CWD + [filename] 
            "stream": None,
        })
        os.makedirs("test_specs", exist_ok=True)
        specs = {
            "hostSpec.json": self.hostSpec,
            "hostAddress.json": self.hostAddress,
            "testUploadSpec.json": self.baseFileSpec
        }
        for file_name, spec_data in specs.items():
            with open(os.path.join("test_specs", file_name), "w") as f:
                json.dump(spec_data, f, indent=4)

    def tearDown(self):
        """
        Remove the temporary test upload directory.
        """
        #shutil.rmtree(self.server_root, ignore_errors=True)
        #shutil.rmtree(self.client_root, ignore_errors=True)


    # A) server control
    def control_server(self, action, spec, expect):
        assert action in ["start","stop"]
        res = UploadService.run(__command=[action], **spec)
        time.sleep(1)
        print(f"control_server -------- {action}")
        listResp = UploadService.run(__command=['list'], **spec)
        print(listResp)
        if type(listResp) == str:
            listResp = json.loads(listResp)
        print(type(listResp))
        if (len(listResp) == 0):
            return "missing"
        status = listResp[ 'http_upload' ]['status']
        time.sleep(2)
        logs = UploadService.run(__command=['logs'], **spec)
        print(f"System logs: \n{logs[0]}\n\n")
        print(f"System Errs: \n{logs[1]}\n\n")
        self.assertIn(status, expect)

    # B) create demo file
    def create_demo(self, filepath, filename, content):
        path = os.path.join(filepath, filename)
        os.makedirs(filepath, exist_ok=True)   
        with open(path, "w") as f:
            f.write(content)
        return path

    def create_demo_folder(self, base_path, num_files=30, depth=2):
        """
        Creates a directory tree `base_path/level0_x/level1_y/...` up to `depth` levels,
        and populates it with `num_files` text files containing deterministic junk content.
        Files are evenly distributed across the leaf directories.
        Returns a list of all created file paths.
        """
        # build nested directory names
        dirs = [f"level{d}" for d in range(depth)]
        # generate all leaf paths
        print(f"MAKING {base_path}")
        os.makedirs(base_path, exist_ok=True)   
        def build_paths(d, prefix):
            if d == depth:
                return [prefix]
            paths = []
            for idx in range(depth):
                paths += build_paths(d+1, os.path.join(prefix, f"{dirs[d]}_{idx}"))
            return paths

        leaf_dirs = build_paths(0, base_path)
        for p in leaf_dirs:
            os.makedirs(p, exist_ok=True)

        # distribute files evenly
        file_paths = []
        for i in range(num_files):
            leaf = leaf_dirs[i % len(leaf_dirs)]
            filename = f"file_{i}.txt"
            content = f"DEMO_CONTENT_{i:03d}\n"
            path = os.path.join(leaf, filename)
            print(path)
            with open(path, "w") as f:
                f.write(content)
            file_paths.append(path)

        return file_paths

    # D) verify payload
    def verify_payload(self, record, ctx, expected):
        with DDBFolder.open_payload(record, ctx, 'r') as s:
            self.assertEqual(s.read(), expected)

    # E) delete & confirm
    def delete_and_confirm(self, record, ctx):
        DDBFolder.delete_file(record, ctx)
        self.assertFalse(DDBFolder.has_file(record, ctx))
        with self.assertRaises(Exception):
            DDBFolder.open_payload(record, ctx, 'r')

    def send_cmd(self, command_id: str, args: dict = None, data: dict = None):
        """
        Validate a Command via BaseData, then invoke it through run_remote.
        Returns the parsed result (not an HTTP Response).
        """
        cmd = UploadService.Command({
            UploadService.Command.f_command_id: command_id,
            UploadService.Command.f_executor_id: "anon",
            UploadService.Command.f_args: args or {},
            UploadService.Command.f_data: data or {},
            UploadService.Command.f_auth: {}
        })
        host_addr = UploadService.tHostAddress(self.hostAddress)
        return UploadService.run_remote(
            hostAddress=dict(host_addr),
            cmd=dict(cmd)
        )

    def http_get(self, path: str, as_host: str = None):
        """
        Simple GET, with optional Host header spoofing.
        """
        url = f"http://{self.hostAddress['host']}:{self.hostAddress['port']}{path}"
        headers = {}
        if as_host:
            headers["Host"] = as_host
        return requests.get(url, headers=headers)
    
    def reset_server(self):
        shutil.rmtree(self.server_root, ignore_errors=True)
        shutil.rmtree(self.client_root, ignore_errors=True)

    def start_server(self):
        """
        Stop any existing job, clean dirs, then start fresh.
        """
        ha = UploadService._init_thenload(UploadService.tHostSpec(self.hostSpec),do_overwrite=False)
        self.control_server("stop", dict(UploadService.tHostSpec(ha)), ["stopped","failed"])
        time.sleep(0.1)
        self.control_server("start", dict(UploadService.tHostSpec(ha)), ["running"])
        time.sleep(0.5)

    #
    #
    #
    #
    # ALL TESTS
    # 

    def test_upload_and_delete(self):
        
        svc = UploadService
        self.control_server('stop', self.hostSpec, ['stopped','failed'])
        time.sleep(1)
        self.control_server('start', self.hostSpec, ['running'])
        time.sleep(1)

        content = "This is a sample content for upload testing.\n"
        demo_path = self.create_demo(self.client_root, self.baseFileSpec['filename'], content)
        basic_site_file = self.create_demo(os.path.join(self.server_root,self.server_upload_test_root), 'index.html', "Some Web data")

        uploaded= UploadService.run( __command=['upload_file'], **self.baseFileSpec,**self.hostAddress)
        ha = UploadService.tHostAddress(self.hostAddress)
        print("test_upload_and_delete : uploaded - ")
        #print(json.dumps(uploaded,indent=4))
        #print(json.dumps(self.baseFileSpec,indent=4))
        has_file = UploadService.run_remote( 
            hostAddress = ha,
            cmd = UploadService.Command(
                command_id="has_file",
                args=UploadService.EntityID(self.baseFileSpec)
            )        
        )
        '''
        upload_report= UploadService.run( __command=['upload_directory'], **self.baseFolderSpec,**self.hostAddress)
        
        
        '''

        print(f"has_file {has_file}")
        assert type(has_file) == bool 
        assert has_file == True
        
        record, ctx =  UploadService.ToDDBFolderInfo(self.baseFileSpec, self.hostSpec)
        self.verify_payload(record, ctx, content)
        self.delete_and_confirm(record, ctx)

        # Should show missing on client side
        #has_file = UploadService.run_remote( 
        #    eid = UploadService.EntityID(self.baseFileSpec), 
        #    hostAddress = UploadService.tHostAddress(self.hostAddress)
        #)
        has_file = UploadService.run_remote( 
            hostAddress = ha,
            cmd = UploadService.Command(
                command_id="has_file",
                args=UploadService.EntityID(self.baseFileSpec)
            )        
        )


        print(f"has_file {has_file}")
        assert type(has_file) == bool 
        assert has_file == False
        self.control_server('stop', self.hostSpec, ['stopped','failed'])



    def test_directory(self):
        return
        svc = UploadService
        print("test_directory host spec:")
        print(json.dumps(self.hostSpec,indent=3))
        shutil.rmtree(self.client_root, ignore_errors=True)
        os.makedirs(self.client_root, exist_ok=True)   
        shutil.rmtree(self.server_root, ignore_errors=True) 
        os.makedirs(self.server_root, exist_ok=True)   

        time.sleep(1)
        self.control_server('stop', self.hostSpec, ['stopped'])
        time.sleep(1)
        self.control_server('start', self.hostSpec, ['running'])
        time.sleep(1)
        fld = self.baseFolderSpec
        # Purge test location
        #os.makedirs(self.client_root+"LLL", exist_ok=True)   

        demo_path = self.create_demo_folder( self.baseFolderSpec[fld.f_stream_source], num_files=30,depth=2)
        upload_report= UploadService.run( __command=['upload_directory'], 
                                         folderData= UploadService.tClientUploadData(self.baseFolderSpec),
                                         hostAddress=UploadService.tHostAddress(self.hostAddress))
        print(json.dumps(upload_report, indent = 2))
        
        def delete_folder_test_service(upload_report, host_spec):
            svc = UploadService

            for idx, raw_transfer in upload_report.items():
                transfer = svc.tTransferProgress(raw_transfer)
                eid = svc.EntityID(transfer[svc.tTransferProgress.f_data])

                record, ctx =  UploadService.ToDDBFolderInfo(eid, host_spec)
                #self.verify_payload(record, ctx, content)
                self.delete_and_confirm(record, ctx)


                #delete_cmd = svc.Command(command_id="delete_file", args=eid)
                #delete_result = svc.run_remote(hostAddress=host_spec, cmd=delete_cmd)
                #if not isinstance(delete_result, bool) or delete_result is not True:
                #    print(f"[ERROR] Deletion failed for {eid} → Response: {delete_result}")
                #    continue
                #assert delete_result == True
                #confirm_cmd = svc.Command(command_id="has_file", args=dict(eid))#

                #confirm_result = svc.run_remote(hostAddress=host_spec, cmd=confirm_cmd)
                #if not isinstance(confirm_result, bool) or confirm_result is not False:
                #    print(f"[ERROR] File still exists after deletion {eid} → Response: {confirm_result}")
                #assert confirm_result == False

        delete_folder_test_service(upload_report, self.hostSpec)
        

    def test_publish_command_sequence(self):
        return
        # 2) Exercise add/list/delete via schema‐validated commands.
        self.start_server()

        # prepare a new site spec and validate
        new_site = UploadService.tPublishedSite({
            "domain": "test.com",
            "entity_id": {
                "filename": self.server_upload_test_root,
                "filepath": ""
            }
        })

        resp = self.send_cmd("add_published", data={'siteSpec':new_site})
        self.assertEqual(resp, True)

        newList = self.send_cmd("list_published")
        self.assertIn("test.com", [p["domain"] for p in newList])

        resp = self.send_cmd("delete_published", data={'siteSpec':{"domain": "test.com"}})
        self.assertEqual(resp, True)


        newList = self.send_cmd("list_published")
        self.assertNotIn("test.com", [p["domain"] for p in newList])

        self.control_server("stop", dict(UploadService.tHostSpec(self.hostSpec)), ["stopped"])


    #
    #
    # BELOW NEEDS TO BE REDONE DUE TO CODE CHANGES
    #
    #
    #
    def create_demo_site(self, folder_name="demo_site"):
        site_dir = os.path.join(self.client_root, folder_name)
        os.makedirs(site_dir, exist_ok=True)
        with open(os.path.join(site_dir, "apple.html"), "w") as f:
            f.write('<html><img src="image.png"></html>')
        with open(os.path.join(site_dir, "test.png"), "wb") as f:
            f.write(b"\x89PNGDATA")
        with open(os.path.join(site_dir, "index.html"), "w") as f:
            f.write('<html><img src="image.png"></html>')
        with open(os.path.join(site_dir, "image.png"), "wb") as f:
            f.write(b"\x89PNGDATA")
        return site_dir

    def test_full_site_publish_and_serve(self):
        shutil.rmtree(self.client_root, ignore_errors=True)
        os.makedirs(self.client_root, exist_ok=True)   
        shutil.rmtree(self.server_root, ignore_errors=True) 
        os.makedirs(self.server_root, exist_ok=True)   
        #print(self.server_root)
        return
        
        self.start_server()
        return
        time.sleep(1)
        
        site_dir = self.create_demo_site()
        ud = UploadService.tClientUploadData
        # upload_directory using validated client spec
        folder_spec = UploadService.tClientUploadData({
            ud.f_stream_source: site_dir,
            ud.f_filepath: "./",
            ud.f_filename: "demo_site",
            ud.f_attrib: {},
            ud.f_token: self.baseFileSpec[ud.f_token],
        })
        validated_folder = UploadService.tClientUploadData(folder_spec)

        upload_report = UploadService.run(
            __command=['upload_directory'],
            folderData=validated_folder,
            hostAddress=UploadService.tHostAddress(self.hostAddress)
        )
        print(json.dumps(upload_report, indent=2))
        #return
        # publish as justingirard.com
        demo_site = os.path.basename(site_dir)
        site_spec = UploadService.tPublishedSite({
            "domain": "justingirard.com",
            "entity_id": {
                "filename": demo_site,
                "filepath": site_dir
            }
        })
        h = UploadService.tHostSpec
        haCurrent = UploadService._init_thenload(UploadService.tHostSpec(self.hostSpec),do_overwrite=False)
        assert len(haCurrent[h.f_published]) == 1, f"Invalid HA 1 {json.dumps(haCurrent)}"
        publish_result = self.send_cmd("add_published", data={'siteSpec':site_spec})
        haCurrent = UploadService._init_thenload(UploadService.tHostSpec(self.hostSpec),do_overwrite=False)
        assert len(haCurrent[h.f_published]) == 2, f"Invalid HA 2 {json.dumps(haCurrent)}"

        self.assertTrue(publish_result is True)

        haCurrent = UploadService._init_thenload(UploadService.tHostSpec(self.hostSpec),do_overwrite=False)
        assert len(haCurrent[h.f_published]) == 2, f"Invalid HA 3 {json.dumps(haCurrent)}"

        self.start_server()
        haCurrent = UploadService._init_thenload(UploadService.tHostSpec(self.hostSpec),do_overwrite=False)
        assert len(haCurrent[h.f_published]) == 2, f"Invalid HA 4 {json.dumps(haCurrent)}"

        # GET index + image via spoofed Host
        resp = self.http_get("/index.html", as_host="justingirard.com")
        
        self.assertEqual(resp.status_code, 200)
        self.assertIn("img src=\"image.png\"", resp.text)

        bin_resp = self.http_get("/image.png", as_host="justingirard.com")
        self.assertEqual(bin_resp.status_code, 200)
        self.assertEqual(bin_resp.content, b"\x89PNGDATA")

        # restart server → published site remains
        self.control_server("stop", dict(self.hostSpec), ["stopped"])
        time.sleep(0.5)
        self.control_server("start", dict(self.hostSpec), ["running"])
        time.sleep(0.5)

        resp = self.http_get("/index.html", as_host="justingirard.com")
        self.assertEqual(resp.status_code, 200)

        # unpublish on the fly
        unpublish_result = self.send_cmd("delete_published", data={"siteSpec": {"domain": "justingirard.com"}})
        self.assertTrue(unpublish_result is True)

        # now should 404
        resp = self.http_get("/index.html", as_host="justingirard.com")
        print(resp.text)
        self.assertEqual(resp.status_code, 404)

        self.control_server("stop", dict(self.hostSpec), ["stopped"])

    def test_directory_children_lifecycle(self):
        return
        self.start_server()

        # 1) Create the empty folder via upload_directory
        UploadService.run(
            __command=["upload_directory"],
            **dict(UploadService.tClientUploadData({
                "token":         self.baseFolderSpec["token"],
                "filename":      "dirtest",
                "filepath":      self.server_upload_test_root,
                "stream_source": os.path.join(self.client_root, "dirtest"),
                "stream":        None
            })),
            **dict(UploadService.tHostAddress(self.hostAddress))
        )

        eid = UploadService.EntityID(filename= "dirtest",
                                     filepath= self.server_upload_test_root)

        # 2) load_object → should have no children
        folder = self.send_cmd("load_object", args=eid)
        self.assertEqual(folder["children_ids"], {})

        # 3) Add two files into that folder
        for name, content in [("a.txt","A"),("b.txt","B")]:
            fp = self.create_demo(self.client_root, name, content)
            UploadService.run(
                __command=["upload_file"],
                **UploadService.tClientUploadData({
                    "token":         self.baseFileSpec["token"],
                    "filename":      name,
                    "filepath":      f"{self.server_upload_test_root}/dirtest",
                    "stream_source": fp,
                    "stream":        None
                }),
                **dict(UploadService.tHostAddress(self.hostAddress))
            )

        # 4) reload folder → exactly 2 children
        folder = self.send_cmd("load_object", args=eid)
        self.assertEqual(len(folder["children_ids"]), 2)

        # 5) delete the first child
        first = next(folder["children_ids"].values())
        
        child_eid = dict(UploadService.EntityID({
            UploadService.EntityID.f_filename: first["filename"],
            UploadService.EntityID.f_filepath: f"{self.server_upload_test_root}/dirtest"
        }))

        self.send_cmd("delete_object", args=child_eid)

        folder = self.send_cmd("load_object", args=eid)
        self.assertEqual(len(folder["children_ids"]), 1)

        # 6) cannot delete non‐empty folder
        with self.assertRaises(Exception):
            self.send_cmd("delete_object", args=eid)

        # 7) delete the remaining file
        rem = next(folder["children_ids"].values())
        rem_eid = dict(UploadService.EntityID({
            UploadService.EntityID.f_filename: rem["filename"],
            UploadService.EntityID.f_filepath: f"{self.server_upload_test_root}/dirtest"
        }))
        self.send_cmd("delete_object", args=rem_eid)

        folder = self.send_cmd("load_object", args=eid)
        self.assertEqual(folder["children_ids"], {})

        # 8) now delete the empty folder itself
        result = self.send_cmd("delete_object", args=eid)
        self.assertTrue(result)

        self.control_server("stop", self.hostSpec, ["stopped"])


        #self.verify_payload(record, ctx, content)
        #self.delete_and_confirm(record, ctx)
        #self.control_server('stop', self.hostSpec, 'stopped')

if __name__ == "__main__":
    #unittest.main()
    unittest.main(defaultTest="TestUploadService.test_upload_and_delete")