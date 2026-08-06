from pathlib import Path

import httpx

from seao_watch.download import discover_resources


def test_ckan_resource_discovery():
    def handler(request):
        assert request.url.params["q"] == "SEAO"
        return httpx.Response(200, json={"success": True, "result": {"results": [{
            "id": "dataset", "resources": [
                {"id": "one", "name": "hebdo_20260727_20260802.json", "url": "https://files.test/week.json"},
                {"id": "two", "name": "documentation.pdf", "url": "https://files.test/doc.pdf"},
            ]}]}})

    config = {"ckan": {"api_url": "https://ckan.test/api/3/action", "query": "SEAO",
                       "resource_pattern": r"hebdo_.*\.json$"}}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        resources = discover_resources(config, client)
    assert [Path(item["name"]).name for item in resources] == ["hebdo_20260727_20260802.json"]

