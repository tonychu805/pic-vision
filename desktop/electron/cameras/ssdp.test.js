// Fixtures are the real thing: the XML below is exactly what the Synology
// BC500 on this network served at http://192.168.1.121:49152/device_desc.xml
// on 2026-09-09, and the scopes are exactly what the TP-Link C200 put in
// its WS-Discovery reply. Invented fixtures would have proved only that
// the parser matches my idea of the format.
import assert from "node:assert/strict";
import { test } from "node:test";
import { declaresCamera, parseDescription } from "./ssdp.js";
import { parseEndpointUuid, parseScopes } from "./discovery.js";

const BC500 = `<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
<specVersion><major>1</major><minor>0</minor></specVersion>
<device>
<deviceType>urn:schemas-upnp-org:device:IPCamera:1</deviceType>
<friendlyName>pic-vision-test-001-BC500</friendlyName>
<manufacturer>Synology</manufacturer>
<manufacturerURL>https://www.synology.com</manufacturerURL>
<modelDescription>Synology Camera BC500</modelDescription>
<modelName>BC500</modelName>
<modelNumber>BC500</modelNumber>
<serialNumber>2310VSRCJY482</serialNumber>
<UDN>uuid:Upnp-IPCamera-1_0-9009D03B7A38</UDN>
<UPC></UPC>
<serviceList></serviceList>
<presentationURL>https://192.168.1.121:443</presentationURL>
</device>
</root>`;

test("a real camera description yields the fields a person recognises", () => {
  const d = parseDescription(BC500);
  assert.equal(d.friendlyName, "pic-vision-test-001-BC500", "the name someone set on the camera");
  assert.equal(d.model, "BC500");
  assert.equal(d.serial, "2310VSRCJY482", "printed on the camera's own body");
  assert.equal(d.manufacturer, "Synology");
  assert.equal(d.udn, "uuid:Upnp-IPCamera-1_0-9009D03B7A38");
  assert.equal(d.webUi, "https://192.168.1.121:443");
});

test("an empty element is absent, not an empty string", () => {
  // <UPC></UPC> and <serviceList></serviceList> are both empty here. A
  // "" would render as a stray separator in the card's detail line.
  assert.equal(parseDescription(BC500).deviceType, "urn:schemas-upnp-org:device:IPCamera:1");
  assert.equal(parseDescription("<device><friendlyName></friendlyName></device>").friendlyName, null);
  assert.equal(parseDescription("<device></device>").serial, null);
});

test("a device that declares itself a camera is believed; others aren't", () => {
  assert.equal(declaresCamera(parseDescription(BC500)), true);
  // The other things that answered SSDP on this network, verbatim.
  assert.equal(declaresCamera({ deviceType: "urn:schemas-upnp-org:device:MediaRenderer:1" }), false);
  assert.equal(declaresCamera({ deviceType: "urn:schemas-upnp-org:device:Basic:1" }), false);
  assert.equal(declaresCamera(null), false);
  assert.equal(declaresCamera({}), false);
});

// --- ONVIF discovery, the other half. The Tapo answers this and not SSDP;
// the Synology answers SSDP and not this.
const C200_REPLY = `<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope><SOAP-ENV:Header>
<wsa:Address>uuid:3fa1fe68-b915-4053-a3e1-782051cfd87a</wsa:Address>
</SOAP-ENV:Header><SOAP-ENV:Body><d:ProbeMatches><d:ProbeMatch>
<d:Types>dn:NetworkVideoTransmitter</d:Types>
<d:Scopes>onvif://www.onvif.org/name/C200 onvif://www.onvif.org/hardware/C200 onvif://www.onvif.org/Profile/Streaming onvif://www.onvif.org/location/Hong%20Kong onvif://www.onvif.org/type/NetworkVideoTransmitter</d:Scopes>
<d:XAddrs>http://192.168.1.115:2020/onvif/device_service</d:XAddrs>
</d:ProbeMatch></d:ProbeMatches></SOAP-ENV:Body></SOAP-ENV:Envelope>`;

test("ONVIF scopes give the name, model and location the camera advertises", () => {
  const scopes = parseScopes(C200_REPLY);
  assert.equal(scopes.name, "C200");
  assert.equal(scopes.hardware, "C200");
  assert.equal(scopes.location, "Hong Kong", "percent-decoded -- it arrives as Hong%20Kong");
});

test("a device's stable uuid survives an address change", () => {
  assert.equal(parseEndpointUuid(C200_REPLY), "uuid:3fa1fe68-b915-4053-a3e1-782051cfd87a");
  // Some devices send it urn-prefixed; same identity either way.
  assert.equal(
    parseEndpointUuid("<wsa:Address>urn:uuid:db58faea-8d0e-4b47-809d-e323a790914d</wsa:Address>"),
    "uuid:db58faea-8d0e-4b47-809d-e323a790914d",
  );
  // The NAS boxes answer discovery with an http XAddr as the address and
  // no uuid -- not an identity, so not reported as one.
  assert.equal(parseEndpointUuid("<wsa:Address>http://Tony_NAS:5357/x</wsa:Address>"), null);
});

test("missing scopes report nothing rather than empty strings", () => {
  // Both NAS boxes on this network answer with no Scopes element at all.
  assert.deepEqual(parseScopes("<d:ProbeMatch><d:XAddrs>http://Tony_NAS:5357/x</d:XAddrs></d:ProbeMatch>"), {
    name: null, hardware: null, location: null,
  });
});
