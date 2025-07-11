#!/usr/bin/env python3
import unittest
import os
import shutil
import time
import requests
from dotenv import load_dotenv
from llm_base_service import LLMProxyService  # your subclass with proxy support
from pathlib import Path
import json
from typing import Any, Dict
from decelium_wallet.commands.BaseData import BaseData

from proxy_service_model import ProxyServiceModel
'''
some proxy_service_model content:
---

class ProxyServiceModel(BaseModel):
    endpoint: str    # e.g. "http://localhost:8003"
    api_key: str
    model_id: str

    def generate(self,
                 messages: List[Dict[str, str]],
                 **kwargs: Any) -> str:
        url = f"{self.endpoint}/v1/chat/completions"
        assert self.endpoint != None
        assert self.model_id != None
        assert messages != None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {"model": self.model_id, "messages": messages, **kwargs}
        print(f"URL OUT : {type(url)}----{url}")
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def stream(self,
               messages: List[Dict[str, str]],
               **kwargs: Any):
        url = f"{self.endpoint}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {"model": self.model_id,
                   "messages": messages,
                   "stream": True,
                   **kwargs}
        r = requests.post(url, json=payload,
                          headers=headers,
                          stream=True,
                          timeout=None)
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith(b"data:"):
                data = line.removeprefix(b"data:").strip()
                if data == b"[DONE]":
                    break
                yield data.decode()


'''
class LMStudioSchemaEntry(BaseData):
    type: str
    default: (Any, None)

class LMStudioConfigSchema(BaseData):
    endpoint: LMStudioSchemaEntry
    api_key: LMStudioSchemaEntry
    model_id: LMStudioSchemaEntry
    def get_keys(self): # Make sure all other keys are entries as well.
        req,opt = super().get_keys()
        req = {"*":LMStudioSchemaEntry}
        return req,opt 

class LMStudioModel(BaseData):
    name: str
    display_name: str
    entrypoint: str
    config_schema: LMStudioConfigSchema

class TestLLMProxyService(unittest.TestCase):
    @staticmethod
    def get_model_config():

        model = LMStudioModel({
            LMStudioModel.name:        "lama-service",
            LMStudioModel.display_name:"LamaService Proxy",
            LMStudioModel.entrypoint:  "model.py",
            LMStudioModel.config_schema: LMStudioConfigSchema({
                LMStudioConfigSchema.endpoint: {
                    LMStudioSchemaEntry.type:    "string",
                    LMStudioSchemaEntry.default: "http://localhost:8003"
                },
                LMStudioConfigSchema.api_key: {
                    LMStudioSchemaEntry.type:    "string",
                    LMStudioSchemaEntry.default: "<<OPENAI_API_KEY>>"
                },
                LMStudioConfigSchema.model_id: {
                    LMStudioSchemaEntry.type:    "string",
                    LMStudioSchemaEntry.default: "gpt-3.5-turbo"
                }
            })
        })
        return model
    



    def test_register(self):

        model = TestLLMProxyService.get_model_config()

        base_dir = Path.home() / ".lmstudio" / "models" / model[LMStudioModel.name]
        base_dir.mkdir(parents=True, exist_ok=True)

        model_json = base_dir / "model.json"
        with model_json.open("w") as f:
            json.dump(dict(model), f, indent=2)

        # verify registration
        self.assertTrue(model_json.exists())
        data = json.loads(model_json.read_text())
        self.assertEqual(data.get("name"), model[LMStudioModel.name])
        self.assertEqual(data.get("entrypoint"), model[LMStudioModel.entrypoint])
        # from proxy_service_model import ProxyServiceModel copy tp model.py
        src = Path(__file__).parent / "proxy_service_model.py"
        dst = base_dir / model[LMStudioModel.entrypoint]
        shutil.copy(src, dst)
        self.assertTrue(dst.exists())        


    def test_chat_completions_via_model(self):

        # set up and start the proxy server
        hostSpec = {
            "protocol":     "http",
            "host":         "127.0.0.1",
            "port":         "8003",
            "url":          "/do_upload",
            "command_uri":  "/cmd",
            "upload_dir":   "./tmp/upload",
            "settings_dir": "./tmp/settings",
            "tokens":       "<<DSH_SERVER_TOKEN_LIST>>",
            "open_ai_key":  "<<OPENAI_API_KEY>>",
            "published":    []
        }
        hostSpec = LLMProxyService.tHostSpec(hostSpec)
        shutil.rmtree(hostSpec["upload_dir"], ignore_errors=True)
        shutil.rmtree(hostSpec["settings_dir"], ignore_errors=True)

        LLMProxyService.run(__command=["stop"], **hostSpec)
        time.sleep(0.2)
        LLMProxyService.run(__command=["start"], **hostSpec)
        time.sleep(0.5)

        # build config for the ProxyServiceModel from our schema
        model_cfg = TestLLMProxyService.get_model_config()
        entries = dict(model_cfg.config_schema)
        print(json.dumps(entries,indent=4))
        #return
        sc = LMStudioConfigSchema
        conf = {
            sc.endpoint: LMStudioSchemaEntry(entries[sc.endpoint]).default,
            sc.api_key:  LMStudioSchemaEntry(entries[sc.api_key]).default,
            sc.model_id: LMStudioSchemaEntry(entries[sc.model_id]).default
        }
        assert conf["endpoint"]
        assert  conf["api_key"]
        assert conf["model_id"]
        proxy_model = ProxyServiceModel(**conf)

        # non-streaming check
        reply = proxy_model.generate([{"role": "user", "content": "Hello, world!"}])
        self.assertIsInstance(reply, str)
        self.assertTrue(reply.strip())

        # streaming check
        stream_iter = proxy_model.stream([{"role": "user", "content": "Hello again!"}])
        collected = ""
        for chunk in stream_iter:
            try:
                data = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            for choice in data.get("choices", []):
                text = choice.get("delta", {}).get("content")
                if text:
                    collected += text

        self.assertTrue(len(collected.strip()) > 3, f"Stream did not yield enough content ->[{collected}]")
        print(f"!!! {collected}")
        with self.assertRaises(StopIteration):
            next(stream_iter)

        # shut down
        LLMProxyService.run(__command=["stop"], **hostSpec)

    def test_chat_completions_direct(self):
        load_dotenv()

        hostSpec = {
            "protocol":     "http",
            "host":         "127.0.0.1",
            "port":         "8003",
            "url":          "/do_upload",
            "command_uri":  "/cmd",
            "upload_dir":   "./tmp/upload",
            "settings_dir": "./tmp/settings",
            "tokens":       "<<DSH_SERVER_TOKEN_LIST>>",
            "open_ai_key": "<<OPENAI_API_KEY>>",
            "published":    []
        }
        hostSpec = LLMProxyService.tHostSpec(hostSpec)
        # clean before start
        shutil.rmtree(hostSpec["upload_dir"], ignore_errors=True)
        shutil.rmtree(hostSpec["settings_dir"], ignore_errors=True)

        # start server
        LLMProxyService.run(__command=["stop"], **hostSpec)
        time.sleep(1)
        LLMProxyService.run(__command=["start"], **hostSpec)
        time.sleep(0.2)
        
        # hit chat completions proxy
        resp = requests.post(
            f"http://{hostSpec['host']}:{hostSpec['port']}/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "Hello, world!"}]
            }
        )
        print(resp.json())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("choices", data)

        # hit models proxy
        resp = requests.get(f"http://{hostSpec['host']}:{hostSpec['port']}/v1/models")
        self.assertEqual(resp.status_code, 200)
        models = resp.json()
        self.assertIsInstance(models, dict)
        self.assertIn("data", models)
        self.assertIsInstance(models["data"], list)

        # hit health endpoint
        resp = requests.get(f"http://{hostSpec['host']}:{hostSpec['port']}/v1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


if __name__ == "__main__":
    #unittest.main()
    from dotenv import load_dotenv
    load_dotenv()         
    #unittest.main(defaultTest="TestLLMProxyService.test_chat_completions_via_model")
    unittest.main(defaultTest="TestLLMProxyService.test_chat_completions_direct")

    #unittest.main(defaultTest="TestLLMProxyService.test_register")

