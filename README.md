Featuritis Docs
===============

Featuritis is a tool to let developers define hierarchies of tasks and to let users prioritize these tasks.  People send their votes to an IRC bot and these are tabulated into a static HTML page.

Tasks should be small, corresponding to what will be a single commit.  (When the 'commit link' field of a task is filled the task is considered done.)  Tasks have a title, parents, children, votes and a brief description.

Featuritis uses plurality voting and people can vote once for as many different tasks as they want. To best represent your interests, only vote for the **smallest components** you are interested in.  Your vote is automatically propagated up and down the tree, so you don't have to worry about micromanaging votes for pre-requisite subtasks.

User commands and syntax
========================

Tasks are identified by `T#NNN` were NNN is an integer.  Every bot command takes place inside a private message with the bot.  All user commands can be shorted to one letter.

## `help / h`

    user> help
    bot> user commands: help vote report search list unvote
    user> help vote
    bot> vote T#XXX (multiple numbers okay)
    user> vote help
    bot> vote T#XXX (multiple numbers okay)

## `vote / v`

Works with commas or spaces as a separator.

    user> vote T#345 T#346
    bot> Done.
    user> vote T#347,T#348,T#34o
    bot> Done.  Not found: T#34o

## `unvote / v`

Identical syntax to `vote`

## `list / l`

Simply shows which tasks have been voted for.

    user> list
    bot> Votes: T#345 T#346 T#347 T#348

## `report / r`

With a task number it details about one task.  Without a task number, an overview for the whole project.

    user> report
    bot> 15 open, 13 closed

## `search / s`

Simple case-insensitive string match of titles and descriptions.

    user> search foobar
    bot> 2 hits: T#345 T#346

Admin commands and syntax
=========================

A bit more complicated and messy.  Dig the source.

Developer notes
===============

The same code base supports both Python2 and Python3.

Launch the bot with `python featuritis.py example.conf` though you should probably read and tweak the conf file first.

Superficially it would appear that tasks can form trees.  In fact the engine can handle generic cyclic graphs.  So if the tree walking code looks like weird paranoid overkill, this is why.

Basic identification services such as passwords appear to be completely missing.  This job is handed off to the IRC server's NickServ instead.  There are also no automatic user registration services.  This is done by manually by admin commands.

The entire bot is built in the [crash-only](https://www.usenix.org/legacy/events/hotos03/tech/full_papers/candea/candea_html/index.html) style.  As such, there is no disk-backed database.  Instead there is an append-only log file that essentially logs all commands sent to the bot.  At start up, these commands are fed through the exact same code paths as the IRC parsers.  This rebuilds the internal data structures.

The append-only log also makes it very easy to roll back to any point in time.  Other bots I've done in this style have used it for infinite arbitrary undo, though Featuritis is unlikely to get that option.

Probably the weirdest part of the code is the split between `featuritis.py` (the frontend) and `feature_backend.py`.  The frontend contains all the basic data structures and mutable state.  The IRC library and internal DB are both in the frontend.  The backend (which is about five times larger) contains all the methods and functions.  By splitting the data and functions, the functions can be tweaked, reloaded and updated at runtime with ease.  You almost never need to shutdown and restart the bot while working on it.  And if the reload fails, it'll tell you as such and keep on using the older version.

