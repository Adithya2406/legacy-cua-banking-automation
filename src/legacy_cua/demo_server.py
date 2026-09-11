"""Local intentionally legacy-style banking demo application."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HTML = r'''<!doctype html>
<html><head><title>Heritage Core 1.0 - Demo Credit Union</title>
<style>body{font-family:Arial;background:#d8d4c8;margin:0}.bar{background:#163a5f;color:white;padding:10px}table.shell{margin:24px auto;background:#eee;border:3px ridge #aaa;width:720px}td{padding:8px}.result{background:white;border:1px inset #888}.hidden{display:none}.modal{position:fixed;inset:20% 25%;background:#fff5cc;border:4px outset #a00;padding:24px}</style></head>
<body><div class="bar">HERITAGE CORE :: MEMBER SERVICING</div>
<table class="shell"><tr><td colspan="3"><b>Inquiry &gt; Customer Portfolio</b></td></tr>
<tr><td><label for="custRefEntry">Customer Reference</label></td><td><input id="custRefEntry" maxlength="5" autocomplete="off"></td><td><button id="inquiryGo">Execute Inquiry</button></td></tr>
<tr><td colspan="3"><div id="noticePane" role="alert" class="hidden"></div></td></tr>
<tr id="portfolioRows" class="hidden"><td colspan="3"><table width="100%" border="1"><tr><th>Product Class</th><th>Masked Account</th><th>Available Amount</th></tr><tr><td>Savings Share</td><td>***4412</td><td id="availAmt" role="status" aria-label="Available Amount" data-output="money">$17,482.91</td></tr></table></td></tr></table>
<div id="supervisorGate" role="dialog" class="modal hidden"><b>Supervisor verification required</b><p>Human operator must confirm this inquiry.</p><button id="supervisorContinue">Supervisor Continue</button></div>
<script>
const input=document.getElementById('custRefEntry'), go=document.getElementById('inquiryGo'), notice=document.getElementById('noticePane'), rows=document.getElementById('portfolioRows'), gate=document.getElementById('supervisorGate'); let slowAttempts=0;
go.onclick=()=>{notice.classList.add('hidden');rows.classList.add('hidden');gate.classList.add('hidden'); if(input.value==='40400'){notice.textContent='No matching customer record';notice.classList.remove('hidden')}else if(input.value==='50000'){notice.textContent='Host system unavailable';notice.classList.remove('hidden')}else if(input.value==='40800' && slowAttempts++===0){notice.textContent='Temporary host delay - retry inquiry';notice.classList.remove('hidden')}else if(input.value==='77777'){gate.classList.remove('hidden')}else{rows.classList.remove('hidden')}};
document.getElementById('supervisorContinue').onclick=()=>{gate.classList.add('hidden');rows.classList.remove('hidden')};
</script></body></html>'''


class DemoHandler(BaseHTTPRequestHandler):
    """Serve the local demo without external services."""

    def do_GET(self) -> None:
        """
        Return the legacy demo application for local requests.

        Input Parameter:
            input_parameter(None): This method uses the request stored by the base class.

        Output Parameter:
            output_parameter(None): This method writes the HTTP response directly.
        """
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """
        Suppress default access logging to keep evidence deterministic.

        Input Parameter:
            format(str): Base-server format string.
            args(object): Base-server format arguments.

        Output Parameter:
            output_parameter(None): This method returns no value.
        """
        del format, args


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """
    Run the local banking demo until interrupted.

    Input Parameter:
        host(str): Bind host.
        port(int): Bind TCP port.

    Output Parameter:
        output_parameter(None): This function blocks while serving.
    """
    ThreadingHTTPServer((host, port), DemoHandler).serve_forever()


def main() -> None:
    """
    Parse command-line options and run the demo server.

    Input Parameter:
        input_parameter(None): This function reads process arguments.

    Output Parameter:
        output_parameter(None): This function returns no value.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    arguments = parser.parse_args()
    serve(arguments.host, arguments.port)


if __name__ == "__main__":
    main()
