#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os, re, time, datetime
from copy import copy, deepcopy
from collections import defaultdict

import string
typable = set(string.ascii_letters + string.digits)

max_indent = 10  # to keep the CSS sane

# these are things you'd expect to be methods of stateful
# but they aren't, so that they can be reloaded at runtime

def find_user(source, user_list):
    name,_,mask = source.partition('!')
    if '!' not in source:
        name,_,mask = source.partition('@')
    name2 = name.lower()
    for u in user_list:
        if name2 not in u.nick:
            continue
        if mask not in u.mask:
            continue
        u.active = name
        u.source = source
        return u
    return None

def find_nick(name, user_list):
    name2 = name.lower()
    for u in user_list:
        if name2 not in u.nick:
            continue
        return u
    return None

def new_task_bg(stateful, task_id, title):
    t = stateful.new_task()
    t.number = int(task_id[2:])
    stateful.next_task = max(stateful.next_task, t.number+1)
    t.title = title
    stateful.tasks[task_id] = t

def new_task(stateful, title):
    t = stateful.new_task()
    t.number = stateful.next_task
    task_id = 'T#%i' % t.number
    stateful.next_task += 1
    t.title = title
    stateful.tasks[task_id] = t
    return task_id

def new_user(stateful, nick, mask):
    u = stateful.new_user()
    u.nick.add(nick.lower())
    u.mask.add(mask)
    u.serial = stateful.next_user
    stateful.next_user += 1
    stateful.users.append(u)

def apply_tree(stateful, user, action, task_id):
    # probably should make this take a number instead of implied 1
    if action not in ['vote', 'unvote', 'star', 'unstar']:
        raise Exception('bad apply_tree call')
    if action == 'vote' and stateful.tasks[task_id].commit:
        return False
    walk = set()
    todo = [task_id]
    while todo:
        i = todo.pop()
        walk.add(i)
        parents = stateful.tasks[i].parents
        todo.extend(list(parents - walk))
        walk.update(parents)
    todo = [task_id]
    while todo:
        i = todo.pop()
        walk.add(i)
        children = stateful.tasks[i].children
        todo.extend(list(children - walk))
        walk.update(children)
    if action == 'vote':
        serial = user.serial
        for t in walk:
            stateful.tasks[t].tree_users.append(serial)
            votes = len(set(stateful.tasks[t].tree_users))
            stateful.tasks[t].votes = votes
    if action == 'unvote':
        serial = user.serial
        for t in walk:
            stateful.tasks[t].tree_users.remove(serial)
            votes = len(set(stateful.tasks[t].tree_users))
            stateful.tasks[t].votes = votes
    if action == 'star':
        for t in walk:
            stateful.tasks[t].tree_stars += 1
    if action == 'unvote':
        for t in walk:
            stateful.tasks[t].tree_stars -= 1
    return True  

def recount_everything(stateful):
    # ugh this is dumb
    for t in stateful.tasks.values():
        t.votes = 0
        t.tree_users = []
        t.tree_stars = 0
    for u in stateful.admins + stateful.users:
        for v in u.votes:
            apply_tree(stateful, u, 'vote', v)
    for t in stateful.tasks:
        for i in range(stateful.tasks[t].stars):
            apply_tree(stateful, None, 'star', t)

def full_coverage(stateful, tree_trunks):
    # this should fail when there are un-accounted for loops
    # for now, don't make high-level loops
    return True

def in_chain(tree, i, child):
    indent = tree[i][3]
    for j in range(i, -1, -1):
        if tree[j][3] != indent:
            continue
        if tree[j][4] == child:
            return True
        indent -= 1
    return False

def build_tree(stateful):
    # assumes counts are good
    tree = []  # (done, stars, votes, indent, task)   not really a tree
    for t_id,t in stateful.tasks.items():
        if t.parents:
            continue
        row = (t.commit is None, t.tree_stars, t.votes, 0, t_id)
        tree.append(row)
    if not full_coverage(stateful, tree):
        pass
    tree.sort()
    tree.reverse()
    i = 0
    while i < len(tree):
        children = stateful.tasks[tree[i][4]].children
        indent = tree[i][3] + 1
        branches = []
        for c_id in children:
            if in_chain(tree, i, c_id):
                continue
            c = stateful.tasks[c_id]
            row = (c.commit is None, c.tree_stars, c.votes, indent, c_id)
            branches.append(row)
        branches.sort()
        branches.reverse()
        while branches:
            # probably a smarter way of doing this
            tree.insert(i+1, branches.pop())
        i += 1
    return tree

def log_raw(stateful, source, message):
    log_tick(stateful)
    if stateful.logfile:
        stateful.logfile.write(source+'\t'+message+'\n')
        stateful.logfile.flush()
        os.fsync(stateful.logfile)

def log_irc(stateful, c, e):
    source = e.source
    message = ' '.join(e.arguments)
    log_raw(stateful, source, message)

# 10 minute timestamp resolution
tick = lambda: time.strftime('# %Y-%m-%d %H:%M', time.localtime())[:-1] + '0'

def xml_escape(s):
    # the sax module messes up profile too much
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def log_tick(stateful):
    now = tick()
    if now == stateful.tick:
        return
    stateful.tick = now
    if stateful.logfile:
        stateful.logfile.write(stateful.tick+'\n')
        stateful.logfile.flush()
        os.fsync(stateful.logfile)

# command parsers and actions
# lots of dumb copy/paste here, refactor!

def new_fn(stateful, user, message):
    help_text = 'new Title of a Task'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    """
    when live, it uses next task_id
    when recorded, the task_id is embedded
    this is to prevent a damaged log file from causing
    massive off by one errors
    """
    title = message.strip()
    # confirm title is new
    for t in stateful.tasks.values():
        if title == t.title:
            stateful.notices.append((user.active, 'error: title exists'))
            return False
    # generate task and id
    if stateful.logfile:  # live/interactive/logging
        task_id = new_task(stateful, title)
    else:  # reloaded playback
        task_id,_,title = message.partition(' ')
        new_task_bg(stateful, task_id, title)
    # report event
    status_message = '%s created %s, %s' % (user.active, task_id, message)
    stateful.notices.append((user.active, status_message))
    stateful.notices.append((stateful.conf.main_channel, status_message))
    # manually log event (deterministic task_id)
    meta_cmd = 'new %s %s' % (task_id, title)
    log_raw(stateful, user.source, meta_cmd)
    render_html(stateful.conf.html_path, stateful)
    render_rss(stateful.conf.rss_path, stateful)
    return False

def finished_fn(stateful, user, message):
    help_text = 'finished T#NNN http://url.of.commit'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    task_id,_,url = message.partition(' ')
    if task_id not in stateful.tasks:
        status_message = 'error: task %s not found' % task_id
        stateful.notices.append((user.active, status_message))
        return False
    stateful.tasks[task_id].commit = url
    status_message = '%s finished %s: %s' % (user.active, task_id, stateful.tasks[task_id].title)
    stateful.notices.append((user.active, status_message))
    stateful.notices.append((stateful.conf.main_channel, status_message))
    recount_everything(stateful)
    return True

def comment_fn(stateful, user, message):
    help_text = 'comment T#XXX [append Text] [insert N Text] [remove N] [swap N M] [show]'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    message = message.split()
    if len(message) < 2:
        stateful.notices.append((user.active, help_text))
        return False
    task_id = message[0]
    command = message[1]
    if task_id not in stateful.tasks:
        status_message = 'error: task %s not found' % task_id
        stateful.notices.append((user.active, status_message))
        return False
    t = stateful.tasks[task_id]
    if command == 'show':
        if len(t.desc) == 0:
            status_message = 'error: no description'
            stateful.notices.append((user.active, status_message))
            return False
        for i,line in enumerate(t.desc):
            status_message = 'line %i: %s' % (i, line)
            stateful.notices.append((user.active, status_message))
        return False
    if command == 'append':
        t.desc.append(' '.join(message[2:]))
        status_message = '%s: %i lines' % (task_id, len(t.desc))
        stateful.notices.append((user.active, status_message))
        return True
    if command == 'insert':
        n = int(message[2])
        t.desc.insert(n, ' '.join(message[3:]))
        status_message = '%s: %i lines' % (task_id, len(t.desc))
        stateful.notices.append((user.active, status_message))
        return True
    if command == 'remove':
        n = int(message[2])
        if n >= len(t.desc):
            status_message = 'error: bad index'
            stateful.notices.append((user.active, status_message))
            return False
        t.desc.pop(n)
        status_message = '%s: %i lines' % (task_id, len(t.desc))
        stateful.notices.append((user.active, status_message))
        return True
    if command == 'swap':
        n = int(message[2])
        m = int(message[3])
        if max(n, m) >= len(t.desc):
            status_message = 'error: bad index'
            stateful.notices.append((user.active, status_message))
            return False
        t.desc[m], t.desc[n] = t.desc[n], t.desc[m]
        status_message = '%s: %i lines' % (task_id, len(t.desc))
        stateful.notices.append((user.active, status_message))
        return True
    stateful.notices.append((user.active, help_text))
    return False

def task_fn(stateful, user, message):
    help_text = 'task T#XXX [childof|c|parentof|p|remove T#NNN] [show]'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    message = message.split()
    if len(message) < 2:
        stateful.notices.append((user.active, help_text))
        return False
    task_id = message[0]
    command = message[1]
    if task_id not in stateful.tasks:
        status_message = 'error: task %s not found' % task_id
        stateful.notices.append((user.active, status_message))
        return False
    t = stateful.tasks[task_id]
    reqs = ', '.join('%s %s' % (t2, stateful.tasks[t2].title) for t2 in t.children)
    pars = ', '.join('%s %s' % (t2, stateful.tasks[t2].title) for t2 in t.parents)
    if command == 'show':
        status_message = 'children: ' + reqs
        stateful.notices.append((user.active, status_message))
        status_message = 'parents: ' + pars
        stateful.notices.append((user.active, status_message))
        return False
    if len(message) < 3:
        stateful.notices.append((user.active, help_text))
        return False
    task_id2 = message[2]
    if task_id2 not in stateful.tasks:
        status_message = 'error: task %s not found' % task_id2
        stateful.notices.append((user.active, status_message))
        return False
    if command == 'childof' or command == 'c':
        stateful.tasks[task_id].parents.add(task_id2)
        stateful.tasks[task_id2].children.add(task_id)
        recount_everything(stateful)
        return True
    if command == 'parentof' or command == 'p':
        stateful.tasks[task_id].children.add(task_id2)
        stateful.tasks[task_id2].parents.add(task_id)
        recount_everything(stateful)
        return True
    if command == 'remove':
        # probably could use a did-something check
        stateful.tasks[task_id].children.discard(task_id2)
        stateful.tasks[task_id].parents.discard(task_id2)
        stateful.tasks[task_id2].children.discard(task_id)
        stateful.tasks[task_id2].parents.discard(task_id)
        recount_everything(stateful)
        return True
    stateful.notices.append((user.active, help_text))
    return False

def doing_fn(stateful, user, message):
    help_text = 'doing [T#XXX|none] [nick]'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    message = message.split()
    if len(message) < 1:
        stateful.notices.append((user.active, help_text))
        return False
    task_id = message[0]
    if task_id.lower() == 'none':
        task_id = None
    if task_id not in stateful.tasks and task_id is not None:
        status_message = 'error: task %s not found' % task_id
        stateful.notices.append((user.active, status_message))
        return False
    target = user.active
    if len(message) == 2:
        target = message[1]
    if not any(target in u.nick for u in stateful.admins):
        status_message = 'error: nick %s not found' % target
        stateful.notices.append((user.active, status_message))
        return False
    for u in stateful.admins:
        if target in u.nick:
            if stateful.tasks[task_id].commit:
                stateful.notices.append((user.active, 'warning: %s already finished' % task_id))
            u.doing = task_id
            status_message = 'set %s to %s' % (target, str(task_id))
            stateful.notices.append((user.active, status_message))
            return True
    stateful.notices.append((user.active, help_text))
    return False

def star_fn(stateful, user, message):
    help_text = 'star T#XXX +|-'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    message = message.split()
    if len(message) != 2:
        stateful.notices.append((user.active, help_text))
        return False
    task_id = message[0]
    stars = message[1]
    if task_id not in stateful.tasks:
        status_message = 'error: task %s not found' % task_id
        stateful.notices.append((user.active, status_message))
        return False
    t = stateful.tasks[task_id]
    old_stars = t.stars
    # laaaaazy
    for char in list(stars):
        if char == '+':
            t.stars += 1
            apply_tree(stateful, user, 'star', task_id)
        if char == '-':
            t.stars -= 1
            apply_tree(stateful, user, 'unstar', task_id)
        #if char in '0123456789':
        #    t.stars = int(char)
    status_message = '%s changed from %i to %i stars' % (task_id, old_stars, t.stars)
    stateful.notices.append((user.active, status_message))
    return True

def admin_fn(stateful, user, message):
    help_text = 'admin [host|register|remove|show nick] [alias oldnick newnick]'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    message = message.split()
    if len(message) < 2:
        stateful.notices.append((user.active, help_text))
        return False
    command = message[0]
    nick1 = message[1].strip()
    nick2 = message[-1].strip()
    u = find_nick(nick1, stateful.admins)
    if u is None:
        u = find_nick(nick1, stateful.users)
    if command == 'show':
        if u is not None:
            status_message = 'Known nicks: ' + ', '.join(u.nick)
            stateful.notices.append((user.active, status_message))
            status_message = 'Known hosts: ' + ', '.join(u.mask)
            stateful.notices.append((user.active, status_message))
        else:
            stateful.notices.append((user.active, 'error: unregistered nick'))
        if nick1 not in stateful.userhosts:
            stateful.notices.append((user.active, 'Unconfirmed host'))
        else:
            stateful.notices.append((user.active, 'Current host: ' + stateful.userhosts[nick1]))
        return False
    if command == 'internal-register':
        if u is not None:
            stateful.notices.append((user.active, '%s already registered' % nick1))
            return False
        new_user(stateful, nick1, nick2)  # nick2 is the userhost
        stateful.userhosts[nick1] = nick2
        return False
    if command == 'internal-remove':
        for u2 in stateful.admins + stateful.users:
            u2.nick.discard(nick1)
            u2.host.discard(nick2)  # nick2 is the userhost
        return False
    if command == 'internal-alias':
        #meta_cmd = 'admin internal-alias %s %s %s' % (nick1, nick2, host2)
        nick2 = message[2]
        host2 = message[3]
        for u2 in stateful.admins + stateful.users:
            if nick1 in u2.nick:
                u2.nick.add(nick2)
                u2.mask.add(host2)
                break
        return False
    if nick1 not in stateful.userhosts:
        status_message = 'No hostname for %s, retrieving...' % nick1
        stateful.notices.append((user.active, status_message))
        stateful.bot.connection.userhost([nick1])
    if nick1 != nick2 and nick2 not in stateful.userhosts:
        status_message = 'No hostname for %s, retrieving...' % nick2
        stateful.notices.append((user.active, status_message))
        stateful.bot.connection.userhost([nick2])
    if nick1 not in stateful.userhosts or nick1 not in stateful.userhosts:
        return False
    if command == 'host':
        stateful.notices.append((user.active, 'Updating hostnames...'))
        stateful.bot.connection.userhost([nick1])
        if nick1 != nick2:
            stateful.bot.connection.userhost([nick2])
        return False
    host1 = stateful.userhosts[nick1]
    host2 = stateful.userhosts[nick2]
    if command == 'register':
        if u is not None:
            stateful.notices.append((user.active, '%s already registered' % nick1))
            return False
        new_user(stateful, nick1, host1)
        stateful.notices.append((user.active, '%s registered' % nick1))
        # manual logging
        meta_cmd = 'admin internal-register %s %s' % (nick1, host1)
        log_raw(stateful, user.source, meta_cmd)
        return False
    if command == 'remove':
        if not any(nick1 in u2.nick for u2 in stateful.admins + stateful.users):
            stateful.notices.append((user.active, 'error: nick %s not found' % nick1))
        if not any(host1 in u2.host for u2 in stateful.admins + stateful.users):
            stateful.notices.append((user.active, 'error: host %s not found' % host1))
        for u2 in stateful.admins + stateful.users:
            u2.nick.discard(nick1)
            u2.host.discard(host1)
        stateful.notices.append((user.active, 'Remove complete.'))
        # manual logging
        meta_cmd = 'admin internal-remove %s %s' % (nick1, host1)
        log_raw(stateful, user.source, meta_cmd)
        return False
    if command == 'alias':
        if not any(nick1 in u2.nick for u2 in stateful.admins + stateful.users):
            stateful.notices.append((user.active, 'error: %s not registered' % nick2))
            return False
        if any(nick2 in u2.nick for u2 in stateful.admins + stateful.users):
            stateful.notices.append((user.active, 'error: %s already registered' % nick2))
            return False
        for u2 in stateful.admins + stateful.users:
            if nick1 in u2.nick:
                u2.nick.add(nick2)
                u2.mask.add(host2)
                stateful.notices.append((user.active, '%s aliased' % nick1))
                # manual logging
                meta_cmd = 'admin internal-alias %s %s %s' % (nick1, nick2, host2)
                log_raw(stateful, user.source, meta_cmd)
                break
        return False
    stateful.notices.append((user.active, help_text))
    return False

def admin_help_fn(stateful, user, message):
    topic,_,message = message.partition(' ')
    generic_admin = 'admin commands: ' + ' '.join(w for w in admin_commands if len(w) > 1)
    generic_user = 'user commands: ' + ' '.join(w for w in user_commands if len(w) > 1)
    if topic == 'h' or topic == 'help' or not topic:
        stateful.notices.append((user.active, generic_admin))
        stateful.notices.append((user.active, generic_user))
        return False
    if topic in admin_commands:
        admin_commands[topic](stateful, user, 'help')
        return False
    if topic in user_commands:
        user_commands[topic](stateful, user, 'help')
        return False
    stateful.notices.append((user.active, generic_admin))
    stateful.notices.append((user.active, generic_user))
    return False

admin_commands = {
    'new': new_fn,
    'finished': finished_fn,
    'comment': comment_fn,
    'task': task_fn,
    'doing': doing_fn,
    'star': star_fn,
    'admin': admin_fn,
    'help': admin_help_fn,
    'n': new_fn,
    'f': finished_fn,
    'c': comment_fn,
    't': task_fn,
    'd': doing_fn,
    'h': admin_help_fn,
}

def vote_fn(stateful, user, message):
    help_text = 'vote T#XXX (multiple numbers okay)'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    message = message.replace(',', ' ').split()
    errs = []
    for t in message:
        if t not in stateful.tasks:
            errs.append(t)
            continue
        user.votes.add(t)
        apply_tree(stateful, user, 'vote', t)
    status_message = 'Done.'
    if errs:
        status_message += '  Not found: ' + ' '.join(errs)
    stateful.notices.append((user.active, status_message))
    if len(errs) == len(message):
        return False
    return True

def unvote_fn(stateful, user, message):
    help_text = 'unvote T#XXX (multiple numbers okay)'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    message = message.replace(',', ' ').split()
    errs = []
    for t in message:
        if t not in stateful.tasks:
            errs.append(t)
            continue
        user.votes.discard(t)
        apply_tree(stateful, user, 'unvote', t)
    status_message = 'Done.'
    if errs:
        status_message += '  Not found: ' + ' '.join(errs)
    stateful.notices.append((user.active, status_message))
    if len(errs) == len(message):
        return False
    return True

def list_fn(stateful, user, message):
    help_text = 'list (takes no options/args)'
    if message == 'help' or message == 'h':
        stateful.notices.append((user.active, help_text))
        return False
    status_message = 'Votes: ' + ' '.join(user.votes)
    stateful.notices.append((user.active, status_message))
    return False

def user_help_fn(stateful, user, message):
    topic,_,message = message.partition(' ')
    generic = 'user commands: ' + ' '.join(w for w in user_commands if len(w) > 1)
    if topic == 'h' or topic == 'help' or not topic:
        stateful.notices.append((user.active, generic))
        return False
    if topic in user_commands:
        user_commands[topic](stateful, user, 'help')
        return False
    stateful.notices.append((user.active, generic))
    return False

def search_fn(stateful, user, message):
    help_text = 'search words'
    if message == 'help' or message == 'h' or not message:
        stateful.notices.append((user.active, help_text))
        return False
    message = message.lower().split()
    hits = set()
    for t,v in stateful.tasks.items():
        if any(w in v.title.lower() for w in message):
            hits.add(t)
            continue
        if any(w in line.lower() for w in message for line in v.desc):
            hits.add(t)
    status_message = '%i hits: %s' % (len(hits), ' '.join(hits))
    stateful.notices.append((user.active, status_message))
    return False

def report_fn(stateful, user, message):
    help_text = 'report, report T#XXX'
    if message == 'help' or message == 'h':
        stateful.notices.append((user.active, help_text))
        return False
    task_id = message.strip()
    if not task_id:
        n_open = 0
        n_closed = 0
        doing = {}
        for t in stateful.tasks.values():
            if t.commit:
                n_closed += 1
            else:
                n_open += 1
        # todo, add the 'doing' report
        status_message = '%i open, %i closed' % (n_open, n_closed)
        stateful.notices.append((user.active, status_message))
        return False
    if task_id not in stateful.tasks:
        status_message = 'error: task %s not found' % task_id
        stateful.notices.append((user.active, status_message))
        return False
    t = stateful.tasks[task_id]
    stateful.notices.append((user.active, 'title: %s' % t.title))
    for line in t.desc:
        status_message = '%s: %s' % (task_id, line)
        stateful.notices.append((user.active, status_message))
    commit = t.commit
    if not commit:
        commit = ''
    else:
        commit = ', commit: %s'
    status_message = '%s: %i votes, %i stars %s' % (t.title, t.votes, t.stars, commit)
    stateful.notices.append((user.active, status_message))
    if not t.commit:
        todo = []
        done = []
        for t2 in t.children:
            if stateful.tasks[t2].commit:
                done.append(t2)
            else:
                todo.append(t2)
        status_message = 'todo: %s' % ', '.join(todo)
        stateful.notices.append((user.active, status_message))
        status_message = 'done: %s' % ', '.join(done)
        stateful.notices.append((user.active, status_message))
    return False

user_commands = {
    'vote': vote_fn,
    'unvote': unvote_fn,
    'list': list_fn,
    'help': user_help_fn,
    'search': search_fn,
    'report': report_fn,
    'v': vote_fn,
    'u': unvote_fn,
    'l': list_fn,
    's': search_fn,
    'r': report_fn,
    'h': user_help_fn,
}

def parse_admin(stateful, user, message):
    topic,_,message = message.partition(' ')
    if topic in admin_commands:
        return admin_commands[topic](stateful, user, message)

def parse_user(stateful, user, message):
    topic,_,message = message.partition(' ')
    if topic in user_commands:
        return user_commands[topic](stateful, user, message)

def pub_action(stateful, c, e):
    message = ' '.join(e.arguments)
    name,_,mask = e.source.partition('!')
    name = name.strip()
    mask = mask.strip()
    # todo, add the handler for admin pub things
    # and maybe a general status thing
    user = find_user(e.source, stateful.admins + stateful.users)
    if user is None:
        return False
    botnick = stateful.conf.nickname
    if message.startswith(botnick + ':') or \
    message.startswith(botnick + ','):
        report = name + ': I only use private messages, /msg ' + botnick + ' help'
        stateful.notices.append((e.target, report))
    return False

def priv_action(stateful, c, e):
    message = ' '.join(e.arguments)
    name,_,mask = e.source.partition('!')
    name = name.strip()
    mask = mask.strip()
    admin = find_user(e.source, stateful.admins)
    updated = False
    if admin is not None:
        status = parse_admin(stateful, admin, message)
        if status:
            log_irc(stateful, c, e)
            updated = True
        status = parse_user(stateful, admin, message)
        if status:
            log_irc(stateful, c, e)
            updated = True
    user = find_user(e.source, stateful.users)
    if user is not None:
        status = parse_user(stateful, user, message)
        if status:
            log_irc(stateful, c, e)
            updated = True
    return updated

def find_dev_doing(stateful):
    for t in stateful.tasks.values():
        t.devs = set()
    for u in stateful.admins:
        nick = u.active
        if not nick:
            nick = list(u.nick)[0]
        if u.doing:
            stateful.tasks[u.doing].devs.add(nick)

task_div_template = """\
<div class="div_row %(task_class)s">
<span class="indent"></span>
<span class="task_id">T#%(task_id)i</span>
<span class="votes">(%(votes)i)</span>
<span class="stars">%(stars)s</span>
<span class="title">%(title)s</span>
<span class="misc">%(misc)s</span>
<div class="desc">%(desc)s</div></div>
"""

def task_div(task, indent):
    task_class = 'open'
    misc = ''
    if task.devs:
        misc = 'devs: ' + ', '.join(task.devs)
        task_class += ' active'
    if task.commit:
        misc = '[<a href="%(url)s" class="commit">commit</a>]' % {'url': task.commit}
        task_class = 'closed'
    task_class += ' indent%i' % indent
    desc = '\n    <br>'.join(task.desc)
    html = task_div_template % \
    {'task_class': task_class,
     'indent': min(indent, max_indent),
     'stars': '★'*task.stars,
     'title': task.title,
     'misc': misc,
     'task_id': task.number,
     'votes': task.votes,
     'desc': desc}
    return html

def render_html(path, stateful):
    if not stateful.logfile:
        return
    find_dev_doing(stateful)
    tree = build_tree(stateful)
    # (done, stars, votes, indent, task)
    html = []
    for _,_,_,indent,t_id in tree:
        html.append(task_div(stateful.tasks[t_id], indent))
    fp = open(path, 'w')
    fp.write('<html><head><meta http-equiv="refresh" content="60">\n')
    fp.write('<title>%s</title>\n' % stateful.conf.project_name)
    fp.write('<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">\n')
    fp.write('<link href="feature.css" rel="stylesheet" type="text/css">\n')
    fp.write('<style type="feature.css" media="all"> @import "main.css"; </style>\n')
    fp.write('<link href="custom.css" rel="stylesheet" type="text/css">\n')
    fp.write('<style type="custom.css" media="all"> @import "main.css"; </style>\n')
    fp.write('<link rel="icon" type="image/png" href="favicon.png">\n')
    fp.write('<link href="rss.xml" rel="alternate" type="application/rss+xml" title="Sitewide RSS Feed">\n')
    fp.write('</head><body>\n')
    fp.write('<div class="rss_link"><a href="rss.xml"><img src="rss16.png" alt="rss link">RSS</a></div>\n')
    fp.write('<div class="title">%s</div>\n' % stateful.conf.project_name)
    if stateful.conf.html_header:
        fp.write('<div class="header">\n')
        fp.write(open(stateful.conf.html_header).read())
        fp.write('</div>\n')
    fp.write('\n'.join(html))
    fp.write('<div class="footer">Powered by <a href="https://github.com/keenerd/featuritis">Featuritis</a></div>')
    fp.write('</body></html>\n')
    fp.close()
    return

def render_rss(path, stateful):
    # since time is not in stateful, do a whole pass over the file
    # could be faster if a seek index was saved
    if not stateful.logfile:
        return
    time_pattern = '^# ([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}:[0-9]{2})$'
    new_pattern = '^.*?\tnew (T#[0-9]*?) (.*)$'
    close_pattern = '^.*?\tclose (T#[0-9]*?) (.*$)'
    time_re = re.compile(time_pattern)
    new_re = re.compile(new_pattern)
    close_re = re.compile(close_pattern)
    current_time = None
    rss_items = []
    months = [None] + 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
    for line in open(stateful.conf.logfile):
        line = line.strip()
        m = time_re.match(line)
        if m:
            t2 = datetime.datetime.strptime(line, '# %Y-%m-%d %H:%M')
            current_time = t2.strftime('%a, %d %b %Y %H:%M:%S GMT')
            continue
        m = new_re.match(line)
        if m:
            task_id, title = m.group(1, 2)
            rss_items.append((current_time, 'new', task_id, title))
            continue
        m = close_re.match(line)
        if m:
            task_id, url = m.group(1, 2)
            rss_items.append((current_time, 'close', task_id, url))
            continue
    rss_items = rss_items[-20:]
    rss_items.reverse()
    fp = open(path, 'w')
    fp.write('<?xml version="1.0" encoding="utf-8"?>\n')
    fp.write('<rss version="2.0">')
    fp.write('<channel>')
    fp.write('<title>Featuritis Log for %s</title>' % xml_escape(stateful.conf.project_name))
    #fp.write('<link>http://example.comm</link>')
    #fp.write('<description>Example description</description>')
    fp.write('<lastBuildDate>%s</lastBuildDate>' % rss_items[0][0])
    fp.write('<generator>Featuritis</generator>')
    fp.write('<docs>http://blogs.law.harvard.edu/tech/rss</docs>\n')
    for c_time, action, t_id, info in rss_items:
        if action not in ('new', 'close'):
            continue
        fp.write('<item>')
        if action == 'new':
            fp.write('<title>New: %s - %s</title>' % \
            (t_id, xml_escape(info)))
        if action == 'closed':
            fp.write('<title>Completed: %s - %s</title>' % \
            (t_id, xml_escape(stateful.tasks[t_id].title)))
            fp.write('<link>%s</link>' % info)
        #fp.write('<description>it is all in the title</description>')
        #fp.write('<guid>meh</giud>')
        fp.write('<pubDate>%s</pubDate>' % c_time)
        fp.write('</item>\n')
    fp.write('</channel></rss>\n')
    fp.close()

def increment(counter):
    ds = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    es = [1679616, 46656, 1296, 36, 1]
    ns = [ds.index(c) for c in counter]
    i = sum(d*e for d,e in zip(ns, es))
    i += 1
    counter2 = ''
    for e in es:
        n = i // e
        counter2 += ds[n]
        i -= n * e
    return counter2



