"""Testklient för Nordviks portal. Hemligheter läses från privata filer."""
import importlib.util
import json
import urllib.request
import urllib.error
from pathlib import Path


class PortalClient:
    def __init__(self, identities, parameters):
        self.state = json.loads(Path(identities).read_text(encoding="utf-8-sig"))
        self.parameters = json.loads(Path(parameters).read_text(encoding="utf-8-sig"))["parameters"]
        self.root = "https://" + self.parameters["functionName"]["value"] + ".azurewebsites.net"
        spec = importlib.util.spec_from_file_location("nordvik_verify", Path(__file__).with_name("verify.py"))
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        self.no_redirect = helper.NoRedirect
        self.tokens = {x["name"]: helper.token(self.state, x) for x in self.state["testApps"]}

    def call(self, path, actor="tenant-a", method="GET", body=None):
        request = urllib.request.Request(self.root + path, method=method,
            headers={"Authorization": "Bearer " + self.tokens[actor], "Content-Type": "application/json"},
            data=None if body is None else json.dumps(body).encode())
        try:
            response = urllib.request.build_opener(self.no_redirect()).open(request, timeout=180)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw
            return response.status, value
