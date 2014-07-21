#! /usr/bin/env python
# -*- coding: utf-8 -*

# licensed GPL3

import os, imp, sys, time, random, threading

import irc
import irc.bot
import irc.strings
from irc.client import ip_numstr_to_quad, ip_quad_to_numstr

from collections import defaultdict

import feature_backend as fb
from imp import reload

if len(sys.argv) != 2 or not os.path.isfile(sys.argv[1]):
    print('featuritis.py config_file')
    sys.exit(1)

conf = imp.load_source("conf", sys.argv[1])


# core data structures are not run-time changable

class Dummy(object):
    pass

class User(object):
    def __init__(self):
        self.serial = None
        self.nick = set()  # case insensitive...
        self.active = ''
        self.mask = set()
        self.votes = set()
        self.source = ''

class Admin(User):
    def __init__(self):
        self.doing = None
        #super().__init__()
        User.__init__(self)

class Task(object):
    def __init__(self):
        self.number = 0
        self.children = set()
        self.parents = set()
        self.votes = 0  # len(set(tree_users))
        self.stars = 0
        self.title = ''
        self.desc = []
        self.commit = None
        self.tree_stars = 0
        self.tree_users = []
        self.devs = set()

class Stateful(object):
    def __init__(self):
        self.users = []  # list of User()
        self.admins = []  # list of User()
        self.tasks = {}  # keyed by task number
        self.logfile = None
        # disable logfile during non-interactive use
        # (also is used as a flag for interactive use)
        self.tick = ''
        self.notices = []  # (nick, message)
        self.conf = conf
        self.next_task = 100
        self.next_user = 1
        self.bot = None
        self.userhosts = {}
        self.seed_admin()
    def seed_admin(self):
        for nicks, hosts in conf.admin_array:
            a1 = Admin()
            a1.nick.update(nicks)
            a1.mask.update(hosts)
            a1.serial = self.next_user
            self.next_user += 1
            self.admins.append(a1)
    # dumb methods to make objects available to backend
    def new_task(self):
        return Task()
    def new_user(self):
        return User()

stateful = Stateful()
bot = None

def reload_log(logfile):
    if stateful.logfile:
        stateful.logfile.close()
    stateful.__init__()
    if not os.path.isfile(logfile):
        print('error:', logfile, 'not found')
        return
    for line in open(logfile):
        if line.startswith('#'):
            continue
        source,_,message = line.strip().partition('\t')
        e = Dummy()
        e.source = source
        e.arguments = [message]
        fb.priv_action(stateful, None, e)
    stateful.notices = []
    stateful.logfile = open(conf.logfile, 'a')

class TestBot(irc.bot.SingleServerIRCBot):
    def __init__(self):
        irc.bot.SingleServerIRCBot.__init__(self, [(conf.server, conf.port)],
            conf.nickname, conf.nickname)
        self.channel = conf.main_channel
        if conf.password:
            self.server_list[0].password = conf.password
        self.connection.add_global_handler(302, self.on_userhost)

    def on_userhost(self, c, e):
        user,_,host = e.arguments[0].partition('=+')
        stateful.userhosts[user] = host

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        for priv,msg in conf.pre_join:
            c.privmsg(priv, msg)
            time.sleep(0.5)
        if conf.channel_key:
            c.join(self.channel, key=conf.channel_key)
        else:
            c.join(self.channel)

    # why not just send messages directly or immediately?
    def send_notices(self):
        c = self.connection
        for nick,message in stateful.notices:
            # todo, split long messages
            c.privmsg(nick, message)
        stateful.notices = []

    def on_privmsg(self, c, e):
        self.check_reload(c, e)
        status = fb.priv_action(stateful, c, e)
        self.send_notices()
        if status:
            fb.render_html(conf.html_path, stateful)
            fb.render_rss(conf.rss_path, stateful)

    def on_pubmsg(self, c, e):
        fb.pub_action(stateful, c, e)
        self.send_notices()

    def check_reload(self, c, e):
        global conf
        nick = e.source.nick
        message = ' '.join(e.arguments)
        if any(nick in nn for nn,hm in conf.admin_array) and message == 'reload-backend':
            try:
                tstart = time.time()
                reload(fb)
                tstop = time.time()
                conf = imp.load_source("conf", sys.argv[1])
                stateful.conf = conf
                fb.recount_everything(stateful)
                fb.render_html(conf.html_path, stateful)
                fb.render_rss(conf.rss_path, stateful)
                c.privmsg(nick, 'Reload successful, %f seconds' % (tstop-tstart))
            except:
                c.privmsg(nick, 'Reload failed.')
            return
        if any(nick in nn for nn,hm in conf.admin_array) and message == 'reload-log':
            try:
                tstart = time.time()
                reload_log(conf.logfile)
                tstop = time.time()
                fb.recount_everything(stateful)
                fb.render_html(conf.html_path, stateful)
                fb.render_rss(conf.rss_path, stateful)
                c.privmsg(nick, 'Reload successful, %f seconds' % (tstop-tstart))
            except:
                c.privmsg(nick, 'Reload failed.')
            return
        if any(nick in nn for nn,hm in conf.admin_array) and message == 'reload-html':
            try:
                tstart = time.time()
                fb.recount_everything(stateful)
                fb.render_html(conf.html_path, stateful)
                fb.render_rss(conf.rss_path, stateful)
                tstop = time.time()
                c.privmsg(nick, 'Reload successful, %f seconds' % (tstop-tstart))
            except:
                c.privmsg(nick, 'Reload failed.')
            return


def main():
    global bot
    reload_log(conf.logfile)
    fb.log_tick(stateful)
    fb.recount_everything(stateful)
    fb.render_html(conf.html_path, stateful)
    fb.render_rss(conf.rss_path, stateful)
    print('Loading complete, connecting to IRC...')
    bot = TestBot()
    stateful.bot = bot
    bot.start()
    stateful.logfile.close()

if __name__ == "__main__":
    main()


