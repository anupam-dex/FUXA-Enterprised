/**
 * 'api/plugin': Plugin API to GET/POST plugin data
 */

var express = require("express");
const authJwt = require('../jwt-helper');
var runtime;
var secureFnc;
var checkGroupsFnc;

module.exports = {
    init: function (_runtime, _secureFnc, _checkGroupsFnc) {
        runtime = _runtime;
        secureFnc = _secureFnc;
        checkGroupsFnc = _checkGroupsFnc;
    },
    app: function () {
        var pluginsApp = express();
        pluginsApp.use(function (req, res, next) {
            if (!runtime.project) {
                res.status(404).end();
            } else {
                next();
            }
        });

        /**
         * GET supported Plugin and status (installed) 
         */
        pluginsApp.get("/api/plugins", secureFnc, function (req, res) {
            const permission = checkGroupsFnc(req);
            if (res.statusCode === 403) {
                runtime.logger.error("api get plugins: Tocken Expired");
            } else if (!authJwt.haveAdminPermission(permission)) {
                res.status(401).json({ error: "unauthorized_error", message: "Unauthorized!" });
                runtime.logger.error("api get plugins: Unauthorized!");
            } else {
                runtime.plugins.getPlugins().then(result => {
                    // res.header("Access-Control-Allow-Origin", "*");
                    // res.header("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept");
                    if (result) {
                        const isRestricted = runtime.settings && (runtime.settings.role === 'view' || runtime.settings.disablePlugins);
                        if (isRestricted) {
                            const restrictedResult = result.map(p => {
                                return Object.assign({}, p, {
                                    dinamic: false,
                                    canRemove: false,
                                    status: p.current ? `Installed (View Mode - Managed by Storage)` : `Disabled on View Server`
                                });
                            });
                            res.json(restrictedResult);
                        } else {
                            res.json(result);
                        }
                    } else {
                        res.end();
                    }
                }).catch(function (err) {
                    if (err.code) {
                        res.status(400).json({ error: err.code, message: err.message });
                    } else {
                        res.status(400).json({ error: "unexpected_error", message: err.toString() });
                    }
                    runtime.logger.error("api get plugins: " + err.message);
                });
            }
        });

        /**
         * POST Plugin
         * Install the plugin
         */
        pluginsApp.post("/api/plugins", secureFnc, function (req, res, next) {
            const permission = checkGroupsFnc(req);
            if (res.statusCode === 403) {
                runtime.logger.error("api post plugins: Tocken Expired");
            } else if (!authJwt.haveAdminPermission(permission)) {
                res.status(401).json({ error: "unauthorized_error", message: "Unauthorized!" });
                runtime.logger.error("api post plugins: Unauthorized");
            } else {
                const isRestricted = runtime.settings && (runtime.settings.role === 'view' || runtime.settings.disablePlugins);
                if (isRestricted) {
                    runtime.logger.warn("api post plugins: Blocked plugin installation attempt on View Server.");
                    return res.status(403).json({
                        error: "view_server_restricted",
                        message: "Plugin installation is restricted to Master Storage Servers. View Servers consume tags via the Storage Server."
                    });
                }

                runtime.plugins.addPlugin(req.body.params, true).then(function (data) {
                    runtime.devices.update();
                    res.end();
                }).catch(function (err) {
                    if (err.code) {
                        res.status(400).json({ error: err.code, message: err.message });
                    } else {
                        res.status(400).json({ error: "unexpected_error", message: err.toString() });
                    }
                    runtime.logger.error("api install plugins: " + err.message);
                });
            }
        });

        /**
         * DELETE Plugin
         * Unistall the plugin
         */
        pluginsApp.delete("/api/plugins", secureFnc, function (req, res, next) {
            const permission = checkGroupsFnc(req);
            if (res.statusCode === 403) {
                runtime.logger.error("api delete plugins: Tocken Expired");
            } else if (!authJwt.haveAdminPermission(permission)) {
                res.status(401).json({ error: "unauthorized_error", message: "Unauthorized!" });
                runtime.logger.error("api delete plugins: Unauthorized");
            } else {
                const isRestricted = runtime.settings && (runtime.settings.role === 'view' || runtime.settings.disablePlugins);
                if (isRestricted) {
                    runtime.logger.warn("api delete plugins: Blocked plugin removal attempt on View Server.");
                    return res.status(403).json({
                        error: "view_server_restricted",
                        message: "Plugin removal is restricted to Master Storage Servers."
                    });
                }

                runtime.plugins.removePlugin(req.query.param).then(function (data) {
                    res.end();
                }).catch(function (err) {
                    if (err.code) {
                        res.status(400).json({ error: err.code, message: err.message });
                    } else {
                        res.status(400).json({ error: "unexpected_error", message: err.toString() });
                    }
                    runtime.logger.error("api delete plugins: " + err.message);
                });
            }
        });
        return pluginsApp;
    }
}