# thinhost

Thin HTTP hosts used in the Decelium microsite workflow.

## Install
pip install thinhost

## What's included
- Simple web server: `decelium_simple_host.simple_web_server`
- Upload host: `decelium_simple_host.simple_upload_host` (requires `decelium_core_data`)
- LLM proxy: `decelium_simple_host.llm_base_service` (requires extra deps)

## Run
python -m decelium_simple_host.simple_web_server
python -m decelium_simple_host.simple_upload_host
python -m decelium_simple_host.llm_base_service
