# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.events import Events
import RPi.GPIO as GPIO
from time import sleep
from flask import jsonify


class ComputerVision3dprinter(octoprint.plugin.StartupPlugin,
                                 octoprint.plugin.EventHandlerPlugin,
                                 octoprint.plugin.TemplatePlugin,
                                 octoprint.plugin.SettingsPlugin,
                                 octoprint.plugin.BlueprintPlugin):

    def initialize(self):
        self._logger.info(
            "Running RPi.GPIO version '{0}'".format(GPIO.VERSION))
        if GPIO.VERSION < "0.6":       # Need at least 0.6 for edge detection
            raise Exception("RPi.GPIO must be greater than 0.6")
        GPIO.setwarnings(False)        # Disable GPIO warnings

    @octoprint.plugin.BlueprintPlugin.route("/underfilled", methods=["GET"])
    def api_get_underfilled(self):
        status = "-1"
        if self.underfill_sensor_enabled():
            status = "0" if self.underfilled() else "1"
        return jsonify(status=status)

    @octoprint.plugin.BlueprintPlugin.route("/overfilled", methods=["GET"])
    def api_get_overfilled(self):
        status = "-1"
        if self.overfill_sensor_enabled():
            status = "1" if self.overfilled() else "0"
        return jsonify(status=status)

    @property
    def underfill_pin(self):
        return int(self._settings.get(["underfill_pin"]))

    @property
    def overfill_pin(self):
        return int(self._settings.get(["overfill_pin"]))

    @property
    def underfill_bounce(self):
        return int(self._settings.get(["underfill_bounce"]))

    @property
    def overfill_bounce(self):
        return int(self._settings.get(["overfill_bounce"]))

    @property
    def underfill_switch(self):
        return int(self._settings.get(["underfill_switch"]))

    @property
    def overfill_switch(self):
        return int(self._settings.get(["overfill_switch"]))

    @property
    def mode(self):
        return int(self._settings.get(["mode"]))

    @property
    def underfilled_gcode(self):
        return str(self._settings.get(["underfilled_gcode"])).splitlines()
			
    @property
    def overfilled_gcode(self):
        return str(self._settings.get(["overfilled_gcode"])).splitlines()
		
    @property
    def underfilled_pause_print(self):
        return self._settings.get_boolean(["underfilled_pause_print"])

    @property
    def overfilled_pause_print(self):
        return self._settings.get_boolean(["overfilled_pause_print"])

    @property
    def send_gcode_only_once(self):
        return self._settings.get_boolean(["send_gcode_only_once"])

    def _setup_sensor(self):
        if self.underfill_sensor_enabled() or self.overfill_sensor_enabled():
            if self.mode == 0:
                self._logger.info("Using Board Mode")
                GPIO.setmode(GPIO.BOARD)
            else:
                self._logger.info("Using BCM Mode")
                GPIO.setmode(GPIO.BCM)

            if self.underfill_sensor_enabled():
                self._logger.info(
                    "Filament Underfill Sensor active on GPIO Pin [%s]" % self.underfill_pin)
                GPIO.setup(self.underfill_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            else:
                self._logger.info("Underfill Sensor Pin not configured")

            if self.overfill_sensor_enabled():
                self._logger.info(
                    "Filament overfill Sensor active on GPIO Pin [%s]" % self.overfill_pin)
                GPIO.setup(self.overfill_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            else:
                self._logger.info("overfill Sensor Pin not configured")

        else:
            self._logger.info(
                "Pins not configured, won't work unless configured!")

    def on_after_startup(self):
        self._logger.info("Filament Sensors Revolutions started")
        self._setup_sensor()

    def get_settings_defaults(self):
        return dict(
            underfill_pin=-1,   # Default is no pin
            underfill_bounce=250,  # Debounce 250ms
            underfill_switch=0,    # Normally Open
            underfilled_gcode='',
            underfilled_pause_print=True,

            overfill_pin=-1,  # Default is no pin
            overfill_bounce=250,  # Debounce 250ms
            overfill_switch=0,  # Normally Closed
            overfilled_gcode='',
            overfilled_pause_print=True,

            mode=0,    # Board Mode
            #send_gcode_only_once=True,  # Default set to False for backward compatibility
        )

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._setup_sensor()

    def underfill_sensor_triggered(self):
        return self.underfill_triggered

    def underfill_sensor_enabled(self):
        return self.underfill_pin != -1

    def overfill_sensor_enabled(self):
        return self.overfill_pin != -1

    def underfilled(self):
        return GPIO.input(self.underfill_pin) != self.underfill_switch

    def overfilled(self):
        return GPIO.input(self.overfill_pin) != self.overfill_switch

    def get_template_configs(self):
        return [dict(type="settings", custom_bindings=False)]

    def on_event(self, event, payload):
        # Early abort in case of out ot filament when start printing, as we
        # can't change with a cold nozzle
        if event is Events.PRINT_STARTED:
            if self.underfill_sensor_enabled() and self.underfilled():
                self._logger.info("Printing aborted: underfilled detected!")
                self._printer.cancel_print()
            if self.overfill_sensor_enabled() and self.overfilled():
                self._logger.info("Printing aborted: filament overfilled!")
                self._printer.cancel_print()

        # Enable sensor
        if event in (
            Events.PRINT_STARTED,
            Events.PRINT_RESUMED
        ):
            if self.underfill_sensor_enabled():
                self._logger.info(
                    "%s: Enabling filament underfill sensor." % (event))
                self.underfill_triggered = 0  # reset triggered state
                GPIO.remove_event_detect(self.underfill_pin)
                GPIO.add_event_detect(
                    self.underfill_pin, GPIO.BOTH,
                    callback=self.underfill_sensor_callback,
                    bouncetime=self.underfill_bounce
                )
            if self.overfill_sensor_enabled():
                self._logger.info(
                    "%s: Enabling filament overfill sensor." % (event))
                self.overfill_triggered = 0  # reset triggered state
                GPIO.remove_event_detect(self.overfill_pin)
                GPIO.add_event_detect(
                    self.overfill_pin, GPIO.BOTH,
                    callback=self.overfill_sensor_callback,
                    bouncetime=self.overfill_bounce
                )

        # Disable sensor
        elif event in (
            Events.PRINT_DONE,
            Events.PRINT_FAILED,
            Events.PRINT_CANCELLED,
            Events.ERROR
        ):
            self._logger.info("%s: Disabling underfilled sensors." % (event))
            if self.underfill_sensor_enabled():
                GPIO.remove_event_detect(self.underfill_pin)
            if self.overfill_sensor_enabled():
                GPIO.remove_event_detect(self.overfill_pin)

    def underfill_sensor_callback(self, _):
        sleep(self.underfill_bounce/1000)

        # If we have previously triggered a state change we are still out
        # of filament. Log it and wait on a print resume or a new print job.
        if self.underfill_sensor_triggered():
            self._logger.info("Sensor callback but no trigger state change.")
            return

        if self.underfilled():
            # Set the triggered flag to check next callback
            self.underfill_triggered = 1
            self._logger.info("Underfill filament!")
            if self.send_gcode_only_once:
                self._logger.info("Sending GCODE only once...")
            else:
                # Need to resend GCODE (old default) so reset trigger
                self.underfill_triggered = 0
            if self.underfilled_pause_print:
                self._logger.info("Pausing print.")
                self._printer.pause_print()
            if self.underfilled_gcode:
                self._logger.info("Sending Underfilled GCODE")
                self._printer.commands(self.underfilled_gcode)
        else:
            self._logger.info("Filament detected!")
            if not self.underfilled_pause_print:
                self.underfill_triggered = 0

    def overfill_sensor_callback(self, _):
        sleep(self.overfill_bounce/1000)

        # If we have previously triggered a state change we are still out
        # of filament. Log it and wait on a print resume or a new print job.
        if self.overfill_sensor_triggered():
            self._logger.info("Sensor callback but no trigger state change.")
            return

        if self.overfilled():
            # Set the triggered flag to check next callback
            self.overfill_triggered = 1
            self._logger.info("Filament overfilled!")
            if self.send_gcode_only_once:
                self._logger.info("Sending GCODE only once...")
            else:
                # Need to resend GCODE (old default) so reset trigger
                self.overfill_triggered = 0
            if self.overfilled_pause_print:
                self._logger.info("Pausing print.")
                self._printer.pause_print()
            if self.overfilled_gcode:
                self._logger.info("Sending overfilled GCODE")
                self._printer.commands(self.overfilled_gcode)
        else:
            self._logger.info("Filament not overfilled!")
            if not self.overfilled_pause_print:
                self.overfill_triggered = 0

    def get_update_information(self):
        return dict(
            filamentrevolutions=dict(
                displayName="Computer Vision 3dprinter",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="katihatefi",
                repo="Octoprint-Filament-Revolutions",
                current=self._plugin_version,

                # update method: pip
                #pip="https://github.com/RomRider/Octoprint-Filament-Revolutions/archive/{target_version}.zip"
            )
        )


__plugin_name__ = "Computer Vision 3dprinter"
__plugin_version__ = "1.0.0"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = ComputerVision3dprinter()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }


def __plugin_check__():
    try:
        import RPi.GPIO
    except ImportError:
        return False

    return True


