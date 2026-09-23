// Version-specific bridge for OpenRPA 1.4.57.13. No PowerShell, shell, or HTTP listener.
// The Python broker is the authenticated loopback HTTP boundary.
using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using OpenRPA.Interfaces.IPCService;

class OpenRpaIpcBridge {
    static int Main(string[] args) {
        Console.InputEncoding = new System.Text.UTF8Encoding(false);
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        try {
            if (!OpenRPAServiceUtil.GetInstance()) throw new Exception("OpenRPA IPC unavailable");
            var service = OpenRPAServiceUtil.RemoteInstance;
            if (args.Length == 1 && args[0] == "ping") {
                Console.WriteLine(JsonConvert.SerializeObject(new { status = service.Ping() }));
            } else if (args.Length == 2 && args[0] == "run") {
                var input = JObject.Parse(Console.In.ReadToEnd());
                var parameters = input.ToObject<Dictionary<string, object>>();
                var result = service.RunWorkflowByIDOrRelativeFilename(args[1], true, parameters);
                Console.WriteLine(JsonConvert.SerializeObject(new { status = "succeeded", output = result }));
            } else if (args.Length == 2 && args[0] == "cancel") {
                Console.WriteLine(JsonConvert.SerializeObject(new { status = "cancel_requested", count = service.KillWorkflows(args[1]) }));
            } else throw new Exception("Unsupported bridge operation");
            return 0;
        } catch (Exception ex) {
            Console.WriteLine(JsonConvert.SerializeObject(new { status = "failed", error = ex.Message }));
            return 1;
        }
    }
}
