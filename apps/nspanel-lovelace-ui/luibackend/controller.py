import logging
import datetime

from pages import LuiPagesGen

LOGGER = logging.getLogger(__name__)

class LuiController(object):

    def __init__(self, ha_api, config, send_mqtt_msg):
        self._ha_api = ha_api
        self._config = config
        self._send_mqtt_msg = send_mqtt_msg

        self._current_page = None
        
        self._pages_gen = LuiPagesGen(ha_api, config, send_mqtt_msg)

        # send panel back to startup page on restart of this script
        self._pages_gen.page_type("pageStartup")
        
        # time update callback
        time = datetime.time(0, 0, 0)
        ha_api.run_minutely(self._pages_gen.update_time, time)
        # weather callback
        weather_interval = 15 * 60 # 15 minutes
        ha_api.run_every(self.weather_update, "now", weather_interval)
        # register callbacks
        self.register_callbacks()

    def startup(self, display_firmware_version):
        LOGGER.info(f"Startup Event; Display Firmware Version is {display_firmware_version}")
        # send time and date on startup
        self._pages_gen.update_time("")
        self._pages_gen.update_date("")

        # send panel to screensaver
        self._pages_gen.page_type("screensaver")
        self.weather_update("")

    def weather_update(self, kwargs):
        we_name = self._config.get("weather")
        unit    = "°C"
        self._pages_gen.update_screensaver_weather(kwargs={"weather": we_name, "unit": unit})

    def register_callbacks(self):
        items = self._config.get_root_page().get_all_items_recursive()
        LOGGER.info(f"Registering callbacks for the following items: {items}")
        for item in items:
            self._ha_api.listen_state(self.state_change_callback, entity_id=item, attribute="all")

    def state_change_callback(self, entity, attribute, old, new, kwargs):
        LOGGER.info(f"Got callback for: {entity}")
        if entity in self._current_page.get_items():
            self._pages_gen.render_page(self._current_page)


    def detail_open(self, detail_type, entity_id):
        if detail_type == "popupShutter":
            self._pages_gen.generate_shutter_detail_page(entity_id)
        if detail_type == "popupLight":
            self._pages_gen.generate_light_detail_page(entity_id)

    def button_press(self, entity_id, button_type, value):
        LOGGER.debug(f"Button Press Event; entity_id: {entity_id}; button_type: {button_type}; value: {value} ")
        # internal buttons
        if(entity_id == "screensaver" and button_type == "enter"):
            # go to first child of root page (default, after startup)
            self._current_page = self._config._page_config.childs[0]
            self._pages_gen.render_page(self._current_page)

        if(button_type == "bNext"):
            self._current_page = self._current_page.next()
            self._pages_gen.render_page(self._current_page)
        if(button_type == "bPrev"):
            self._current_page = self._current_page.prev()
            self._pages_gen.render_page(self._current_page)
        if(button_type == "bExit"):
            self._pages_gen.render_page(self._current_page)
        
        # buttons with actions on HA
        if button_type == "OnOff":
            if value == "1":
                self._ha_api.turn_on(entity_id)
            else:
                self._ha_api.turn_off(entity_id)

        # for shutter / covers
        if button_type == "up":
            self._ha_api.get_entity(entity_id).call_service("open_cover")
        if button_type == "stop":
            self._ha_api.get_entity(entity_id).call_service("stop_cover")
        if button_type == "down":
            self._ha_api.get_entity(entity_id).call_service("close_cover")
        if button_type == "positionSlider":
            pos = int(value)
            self._ha_api.get_entity(entity_id).call_service("set_cover_position", position=pos)

        if button_type == "button":
            if entity_id.startswith('scene'):
                self._ha_api.get_entity(entity_id).call_service("turn_on")
            elif entity_id.startswith('light') or entity_id.startswith('switch') or entity_id.startswith('input_boolean'):
                self._ha_api.get_entity(entity_id).call_service("toggle")
            else:
                self._ha_api.get_entity(entity_id).call_service("press")

        # for media page
        if button_type == "media-next":
            self._ha_api.get_entity(entity_id).call_service("media_next_track")
        if button_type == "media-back":
            self._ha_api.get_entity(entity_id).call_service("media_previous_track")
        if button_type == "media-pause":
            self._ha_api.get_entity(entity_id).call_service("media_play_pause")
        if button_type == "hvac_action":
            self._ha_api.get_entity(entity_id).call_service("set_hvac_mode", hvac_mode=value)
        if button_type == "volumeSlider":
            pos = int(value)
            # HA wants this value between 0 and 1 as float
            pos = pos/100
            self._ha_api.get_entity(entity_id).call_service("volume_set", volume_level=pos)

        # for light detail page
        if button_type == "brightnessSlider":
            # scale 0-100 to ha brightness range
            brightness = int(scale(int(value),(0,100),(0,255)))
            self._ha_api.get_entity(entity_id).call_service("turn_on", brightness=brightness)
        if button_type == "colorTempSlider":
            entity = self._ha_api.get_entity(entity_id)
            #scale 0-100 from slider to color range of lamp
            color_val = scale(int(value), (0, 100), (entity.attributes.min_mireds, entity.attributes.max_mireds))
            self._ha_api.get_entity(entity_id).call_service("turn_on", color_temp=color_val)
        if button_type == "colorWheel":
            self._ha_api.log(value)
            value = value.split('|')
            color = pos_to_color(int(value[0]), int(value[1]))
            self._ha_api.log(color)
            self._ha_api.get_entity(entity_id).call_service("turn_on", rgb_color=color)
        
        # for climate page
        if button_type == "tempUpd":
            temp = int(value)/10
            self._ha_api.get_entity(entity_id).call_service("set_temperature", temperature=temp)