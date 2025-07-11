
try:
    from simple_upload_host import UploadService
except:
    from .simple_upload_host import UploadService

import os, sys
import httpx
from flask import Response, request
from processing_graph.ProcessingNode import ProcessingNode
class LLMProxyService(UploadService):
 
    @classmethod
    def _after_launch_endpoints(cls, app, hostSpec):
        hostSpec = cls.tHostSpec(hostSpec)     
        openai_key = hostSpec.get(hostSpec.f_open_ai_key, None)
        if not openai_key:
            raise RuntimeError('openai_api_key is not set in hostSpec')

        client = httpx.Client(
            base_url='https://api.openai.com',
            headers={'Authorization': f'Bearer {openai_key}'}
        )
     
        def _proxy(path: str):
            body    = request.get_data()
            payload = request.get_json(silent=True) or {}

            if payload.get("stream", False):
                def generate():
                    with client.stream(
                        "POST", path,
                        content=body,
                        headers={"Content-Type":"application/json"},
                        timeout=None
                    ) as resp:
                        for chunk in resp.iter_bytes():
                            yield chunk
                return Response(generate(), content_type="text/event-stream")

            resp = client.post(path, content=body, headers={"Content-Type":"application/json"})
            return Response(resp.content, status=resp.status_code,
                            content_type=resp.headers.get("content-type"))



        def _proxy_models():
                    resp = client.get('/v1/models')
                    return Response(
                        resp.content,
                        status=resp.status_code,
                        content_type=resp.headers.get("content-type")
                    )

        app.add_url_rule(
            '/v1/models',
            endpoint='proxy_models',
            view_func=_proxy_models,
            methods=['GET']
        )

        app.add_url_rule(
            '/v1',
            endpoint='health',
            view_func=lambda: Response(
                '{"status":"ok"}',
                status=200,
                content_type='application/json'
            ),
            methods=['GET']
        )

        # register both endpoints
        app.add_url_rule(
            '/v1/chat/completions',
            endpoint='proxy_chat',
            view_func=lambda: _proxy('/v1/chat/completions'),
            methods=['POST']
        )
        app.add_url_rule(
            '/v1/completions',
            endpoint='proxy_completions',
            view_func=lambda: _proxy('/v1/completions'),
            methods=['POST']
        )    
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()     
    LLMProxyService.run_cli()
# python llm_base_service.py launch [[server=./test_specs/hostSpec.json]] -- For a quick test
# python llm_base_service.py start "[[server=./test_specs/hostSpec.json]]" -- deploy job to nodejobs
# open-webui serve UI layer (rests on service)
# TODO wrap up with retry and uptime monitor