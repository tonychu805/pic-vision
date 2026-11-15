// The English table: every area's strings, merged. Add a new area under
// strings/ and list it here and in zh-TW.js -- the parity test fails if the
// two languages drift.
import * as common from "./strings/common.js";
import * as cameras from "./strings/cameras.js";
import * as detail from "./strings/detail.js";
import * as cloud from "./strings/cloud.js";
import * as settings from "./strings/settings.js";
import * as tools from "./strings/tools.js";
import * as main from "./strings/main.js";
import * as log from "./strings/log.js";

export const en = { ...common.en, ...cameras.en, ...detail.en, ...cloud.en, ...settings.en, ...tools.en, ...main.en, ...log.en };
