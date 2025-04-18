#!/usr/bin/env python3
import unittest
import os
import time
import shutil
import json
from dotenv import load_dotenv
from decelium_core_data.DDBFolder import DDBFolder  
 
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
        self.server_upload_root = './upload_root/'
        #shutil.rmtree(self.server_root, ignore_errors=True)
        #shutil.rmtree(self.client_root, ignore_errors=True)

        # Host specification used by UploadService.tHostSpec and tHostAddress
        self.hostSpec = {
            "HOST_NOTE_IGNORE":"This file is secret on the server",
            "web_html_dir":f"{self.server_root}/static_html",
            "upload_dir":f"{self.server_root}/flask_uploaded",
            "url":"/do_upload",
            "command_uri":"/cmd",
            "port":"5000",
            "host":"0.0.0.0",
            "protocol":"http",
            "tokens":"<<DSH_SERVER_TOKEN_LIST>>"
        }

        self.hostAddress = {
            "ADDY_NOTE_IGNORE":"This file is given to a http client",
            "protocol": "http",
            "port": "5000",
            "host": "localhost",
            "url": "/do_upload",
            "command_uri": "/cmd"
        }
        # File specification used by UploadService.tClientUploadData.
        self.baseFileSpec = UploadService.tClientUploadData({
            "FILE_NOTE_IGNORE":"This is the required data for a test upload",    
            "token": "<<DSH_CLIENT_TOKEN>>",
            "filename": "demo_file_2.txt",
            "filepath": self.server_upload_root,
            "stream_source": f"{self.client_root}/demo_file_2.txt", # We can use stream source to lazy define the stream data, or store references.
            "stream": None,
            "do_overwrite":True
        })
        self.baseFolderSpec = UploadService.tClientUploadData({
            "FILE_NOTE_IGNORE":"This is the required data for a test upload",    
            "token": "<<DSH_CLIENT_TOKEN>>",
            "filename": "demo_folder",
            "filepath":  self.server_upload_root, 
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
        res = UploadService.run(__command=[action], **spec)
        time.sleep(1)
        status = UploadService.run(__command=['list'])[ 'http_upload' ]['status']
        self.assertEqual(status, expect)

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

    def test_upload_and_delete(self):
        return
        svc = UploadService
        self.control_server('stop', self.hostSpec, 'stopped')
        self.control_server('start', self.hostSpec, 'running')

        content = "This is a sample content for upload testing.\n"
        demo_path = self.create_demo(self.client_root, self.baseFileSpec['filename'], content)

        uploaded= UploadService.run( __command=['upload_file'], **self.baseFileSpec,**self.hostAddress)

        has_file = UploadService._remote_has_file( 
            eid = UploadService.EntityID(self.baseFileSpec), 
            hostAddress = UploadService.tHostAddress(self.hostAddress)
        )
        print(f"has_file {has_file}")
        assert type(has_file) == bool 
        assert has_file == True
        
        record, ctx =  UploadService.ToDDBFolderInfo(self.baseFileSpec, self.hostSpec)
        self.verify_payload(record, ctx, content)
        self.delete_and_confirm(record, ctx)

        # Should show missing on client side
        has_file = UploadService._remote_has_file( 
            eid = UploadService.EntityID(self.baseFileSpec), 
            hostAddress = UploadService.tHostAddress(self.hostAddress)
        )
        print(f"has_file {has_file}")
        assert type(has_file) == bool 
        assert has_file == False
        self.control_server('stop', self.hostSpec, 'stopped')

    def test_directory(self):
        
        svc = UploadService
        self.control_server('stop', self.hostSpec, 'stopped')
        self.control_server('start', self.hostSpec, 'running')
        fld = self.baseFolderSpec
        # Purge test location
        shutil.rmtree(self.client_root, ignore_errors=True)
        os.makedirs(self.client_root, exist_ok=True)   
        shutil.rmtree(self.server_root, ignore_errors=True)
        os.makedirs(self.server_root, exist_ok=True)   
        #os.makedirs(self.client_root+"LLL", exist_ok=True)   

        demo_path = self.create_demo_folder( self.baseFolderSpec[fld.f_stream_source], num_files=30,depth=2)
        upload_report= UploadService.run( __command=['upload_directory'], **self.baseFolderSpec,**self.hostAddress)
        print(json.dumps(upload_report, indent = 2))
        return

        record, ctx =  UploadService.ToDDBFolderInfo(self.baseFolderSpec, self.hostSpec)


        #self.verify_payload(record, ctx, content)
        #self.delete_and_confirm(record, ctx)
        self.control_server('stop', self.hostSpec, 'stopped')

if __name__ == "__main__":
    unittest.main()