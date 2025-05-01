from dateutil import tz
import datetime
import threading
import logging
import libs.panel_cmd
from scheduler import Scheduler
import scheduler.trigger as trigger
import time
import babel.dates
from ha_cards import Screensaver, card_factory, detail_open
import ha_control

class LovelaceUIPanel:

    def __init__(self, name_panel, settings_panel, msg_out_queue):
        self.name = name_panel
        self.settings = settings_panel
        self.msg_out_queue = msg_out_queue
        self.sendTopic = self.settings["panelSendTopic"]
        self.recvTopic = self.settings["panelRecvTopic"]
        self.model = self.settings.get("model", "eu")

        self.temp_unit = self.settings.get("temp_unit", "celsius")

        self.current_card = None
        self.privious_cards = []
        self.cards = {}
        self.hidden_cards = {}
        self.screensaver = None
        self.navigate_keys = {}
        self.entity_iids = {}

        # generate cards for input settings
        for c in self.settings.get("cards"):
            iid, card = card_factory(self.settings["locale"], c, self)
             # Check if we acually got a card
            if card:
                self.cards[iid] = card
                # collect nav keys of cards
                if card.navigate_key:
                    self.navigate_keys[card.navigate_key] = iid
                # collect iids of entities
                for e in card.get_iid_entities():
                    self.entity_iids[e[0]] = e[1]

        # setup prev and next iids
        top_level_cards = list(self.cards.values())
        card_iids = [card.iid for card in top_level_cards]
        prev_iids = card_iids[-1:] + card_iids[:-1]
        next_iids = card_iids[1:] + card_iids[: 1]
        if len(card_iids) > 1:
            for prev_iids, card, next_iids in zip(prev_iids, top_level_cards, next_iids):
                (card.iid_prev, card.iid_next) = (prev_iids, next_iids)

        # generate cards for input settings
        for c in self.settings.get("hiddenCards", []):
            iid, card = card_factory(self.settings["locale"], c, self)
            card.hidden = True
            self.hidden_cards[iid] = card
            # collect nav keys of cards
            if card.navigate_key:
                self.navigate_keys[card.navigate_key] = iid
            # collect iids of entities
            for e in card.get_iid_entities():
                self.entity_iids[e[0]] = e[1]

        self.schedule = Scheduler()
        self.schedule.minutely(datetime.time(second=0), self.update_time)
        self.schedule.hourly(datetime.time(
            minute=0, second=0), self.update_date)
        schedule_thread = threading.Thread(target=self.schedule_thread_target)
        schedule_thread.daemon = True
        schedule_thread.start()

        # check if ha state cache is already populated
        ha_control.wait_for_ha_cache()

        #request templates on cards
        if isinstance(self.settings.get("sleepBrightness",""), str) and self.settings.get("sleepBrightness", "").startswith("ha:"):
            libs.home_assistant.cache_template(self.settings.get("sleepBrightness"))
        if isinstance(self.settings.get("sleepBrightness",""), str) and self.settings.get("screenBrightness", "").startswith("ha:"):
            libs.home_assistant.cache_template(self.settings.get("screenBrightness"))
        for c in self.cards.values():
            if hasattr(c, "qrcode"):
                if c.qrcode.startswith("ha:"):
                    libs.home_assistant.cache_template(c.qrcode)
            for e in c.entities:
                e.prerender()
        for c in self.hidden_cards.values():
            if hasattr(c, "qrcode"):
                if c.qrcode.startswith("ha:"):
                    libs.home_assistant.cache_template(c.qrcode)
            for e in c.entities:
                e.prerender()
        self.screensaver = Screensaver(self.settings["locale"], self.settings["screensaver"], self)
        if self.screensaver.statusIcon1:
            self.screensaver.statusIcon1.prerender()
        if self.screensaver.statusIcon2:
            self.screensaver.statusIcon2.prerender()
        for e in self.screensaver.entities:
            e.prerender()

        libs.panel_cmd.page_type(self.msg_out_queue, self.sendTopic, "pageStartup")


    def schedule_thread_target(self):
        while True:
            self.schedule.exec_jobs()
            time.sleep(1)

    def update_time(self):
        use_timezone = tz.gettz(self.settings["timeZone"])
        time_string = datetime.datetime.now(
            use_timezone).strftime(self.settings["timeFormat"])
        libs.panel_cmd.send_time(self.msg_out_queue, self.sendTopic, time_string)

    def update_date(self):
        dateformat = self.settings["dateFormat"]
        date_string = babel.dates.format_date(
            datetime.datetime.now(), dateformat, locale=self.settings["locale"])
        libs.panel_cmd.send_date(self.msg_out_queue, self.sendTopic, date_string)

    def searchCard(self, iid):
        if iid in self.navigate_keys:
            iid = self.navigate_keys[iid]
        if iid in self.cards:
            return self.cards[iid]
        if iid in self.hidden_cards:
            return self.hidden_cards[iid]

    def ha_event_callback(self, entity_id):
        #logging.debug(f"{self.name} {entity_id} updated/state changed")
        if self.current_card and entity_id in self.current_card.get_entities():
            self.render_current_page(requested=True)

            # send update for detail popup in case it's open
            etype = entity_id.split('.')[0]
            if etype in ['light', 'timer', 'cover', 'input_select', 'select', 'fan', 'climate']:
                # figure out iid of entity
                entity_id_iid = ""
                for e in self.current_card.entities:
                    if entity_id == e.entity_id:
                        entity_id_iid = f'iid.{e.iid}'

                    effectList = None
                    if etype=="light":
                        effectList = e.config.get("effectList")
                if etype == 'light':
                    libs.panel_cmd.entityUpdateDetail2(self.msg_out_queue, self.sendTopic, detail_open(self.settings["locale"], "popupInSel", entity_id, entity_id_iid, self.msg_out_queue, sendTopic=self.sendTopic, options_list=effectList))
                    libs.panel_cmd.entityUpdateDetail(self.msg_out_queue, self.sendTopic, detail_open(self.settings["locale"], "popupLight", entity_id, entity_id_iid, self.msg_out_queue, sendTopic=self.sendTopic))
                elif etype in ['input_select', 'media_player']:
                    libs.panel_cmd.entityUpdateDetail2(self.msg_out_queue, self.sendTopic, detail_open(self.settings["locale"], etype, entity_id, entity_id_iid, self.msg_out_queue, sendTopic=self.sendTopic))
                else:
                    libs.panel_cmd.entityUpdateDetail(self.msg_out_queue, self.sendTopic, detail_open(self.settings["locale"], etype, entity_id, entity_id_iid, self.msg_out_queue, sendTopic=self.sendTopic))

        involved_entities = ha_control.calculate_dim_values(
            self.settings.get("sleepTracking"),
            self.settings.get("sleepTrackingZones", ["not_home", "off"]),
            self.settings.get("sleepBrightness"),
            self.settings.get("screenBrightness"),
            self.settings.get("sleepOverride"),
            return_involved_entities=True
        )
        if entity_id in involved_entities:
            self.dimmode()


    def render_current_page(self, switchPages=False, requested=False):
        if not self.current_card:
            return
        if switchPages:
            libs.panel_cmd.page_type(self.msg_out_queue, self.sendTopic, self.current_card.type)
        if requested:
            self.current_card.render()

    def dimmode(self):
        # send dimmode
        dimValue, dimValueNormal = ha_control.calculate_dim_values(
            self.settings.get("sleepTracking"),
            self.settings.get("sleepTrackingZones", ["not_home", "off"]),
            self.settings.get("sleepBrightness"),
            self.settings.get("screenBrightness"),
            self.settings.get("sleepOverride"),
        )

        backgroundColor = self.settings.get("defaultBackgroundColor", "ha-dark")
        if backgroundColor == "ha-dark":
            backgroundColor = 6371
        elif backgroundColor == "black":
            backgroundColor = 0
        fontColor = ""
        featExperimentalSliders = self.settings.get("featExperimentalSliders", 0)
        libs.panel_cmd.dimmode(self.msg_out_queue, self.sendTopic, dimValue, dimValueNormal, backgroundColor, fontColor, featExperimentalSliders)

    def get_default_card(self):
        defaultCard = self.settings.get("defaultCard")
        if defaultCard and "." in defaultCard:
            card = self.searchCard(defaultCard.split(".")[1])
            if card:
                return card
        return list(self.cards.values())[0]

    def customrecv_event_callback(self, msg):
        logging.debug("Recv Message from NsPanel (%s): %s", self.name, msg)
        msg = msg.split(",")
        # run action based on received command
        if msg[0] == "event":
            if msg[1] == "startup":
                # TODO: Handle Update Messages
                self.update_date()
                self.update_time()

                self.current_card = self.screensaver
                self.render_current_page(switchPages=True)

                # send sleepTimeout
                sleepTimeout = self.settings.get("sleepTimeout", 20)
                if self.current_card.config.get("sleepTimeout"):
                    sleepTimeout = self.current_card.config.get("sleepTimeout")
                libs.panel_cmd.timeout(self.msg_out_queue, self.sendTopic, sleepTimeout)
                self.dimmode()

            if msg[1] == "sleepReached":
                self.privious_cards.append(self.current_card)
                self.current_card = self.screensaver
                self.render_current_page(switchPages=True)
            if msg[1] == "renderCurrentPage":
                self.render_current_page(requested=True)
            if msg[1] == "buttonPress2":
                entity_id = msg[2]
                if entity_id == "":
                    return
                btype = msg[3]
                value = msg[4] if len(msg) > 4 else None
                if btype == "bExit":
                    if entity_id in ["screensaver", "screensaver2"] and self.settings.get("screensaver").get("doubleTapToUnlock") and value == "1":
                        return

                    # in case privious_cards is empty add a default card
                    if len(self.privious_cards) == 0:
                        self.privious_cards.append(self.get_default_card())

                    if self.settings.get("defaultCard") and entity_id in ["screensaver", "screensaver2"]:
                        logging.debug("Defaulting to card %s", self.settings.get("defaultCard"))
                        self.privious_cards = [self.get_default_card()]

                    self.current_card = self.privious_cards.pop()
                    self.render_current_page(switchPages=True)
                    return

                # replace iid with real entity id
                if entity_id.startswith("iid."):
                    iid = entity_id.split(".")[1]
                    for e in self.current_card.entities:
                        if e.iid == iid:
                            entity_id = e.entity_id
                            entity_config = e.config

                match btype:
                    case 'button':
                        match entity_id.split(".")[0]:
                            # handle internal stuff
                            case 'navigate':
                                card_iid = entity_id.split(".")[1]
                                if card_iid == "UP":
                                    if len(self.privious_cards) == 0:
                                        self.privious_cards.append(self.get_default_card())
                                    self.current_card = self.privious_cards.pop()
                                    self.render_current_page(switchPages=True)
                                else:
                                    self.privious_cards.append(self.current_card)
                                    self.current_card = self.searchCard(card_iid)
                                    self.render_current_page(switchPages=True)
                            # send ha stuff to ha
                            case _:
                                ha_control.handle_buttons(entity_id, btype, value, entity_config=entity_config)
                    case 'cardUnlock-unlock':
                        card_iid = entity_id.split(".")[1]
                        if int(self.current_card.config.get("pin")) == int(value):
                            self.privious_cards.append(self.current_card)
                            self.current_card = self.searchCard(card_iid)
                            self.render_current_page(switchPages=True)
                    case 'mode-light':
                        ha_control.handle_buttons(entity_id, btype, value, entity_config=entity_config)
                    case _:
                        ha_control.handle_buttons(entity_id, btype, value)

            if msg[1] == "pageOpenDetail":
                entity_id = msg[3]
                # replace iid with real entity id
                if entity_id.startswith("iid."):
                    iid = entity_id.split(".")[1]
                    for e in self.current_card.entities:
                        if e.iid == iid:
                            entity_id = e.entity_id
                            effectList = None
                            if entity_id.startswith("light"):
                                effectList = e.config.get("effectList")
                if msg[2] == "popupInSel": #entity_id.split(".")[0] in ['input_select', 'media_player']:
                    libs.panel_cmd.entityUpdateDetail2(self.msg_out_queue, self.sendTopic, detail_open(self.settings["locale"], msg[2], entity_id, msg[3], self.msg_out_queue, sendTopic=self.sendTopic, options_list=effectList))
                else:
                    libs.panel_cmd.entityUpdateDetail(self.msg_out_queue, self.sendTopic, detail_open(self.settings["locale"], msg[2], entity_id, msg[3], self.msg_out_queue, sendTopic=self.sendTopic))


