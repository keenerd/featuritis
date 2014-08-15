Featuritis Docs
===============

Featuritis is a tool to let developers define hierarchies of tasks and to let users prioritize these tasks.  People send their votes to an IRC bot and these are tabulated into a static HTML page.

Tasks should be small, corresponding to what will be a single commit.  (When the 'commit link' field of a task is filled the task is considered done.)  Tasks have a title, parents, children, votes and a brief description.

Featuritis uses plurality voting and people can vote once for as many different tasks as they want. To best represent your interests, only vote for the **smallest components** you are interested in.  Your vote is automatically propagated up and down the tree, so you don't have to worry about micromanaging votes for pre-requisite subtasks.

If you want to see an example of it in action, here is an [IndieGoGo for RTL-SDR](https://www.indiegogo.com/projects/a-month-of-rtl-sdr/x/8229940) and the paired [Featuritis status page](http://igg.kmkeen.com/).

FOSS Funding
============

Most FOSS funding models are very hard to get behind.  Almost every model has at least three of the following issues:

* **Require effective marketing.**  If people don't know you are accepting money, they won't donate any.
* **A slow trickle of income.**  It might be a long time until the generous see results from their donation.
* **Jarring incentives.**  Most fundraisers try to emulate the incentives used by (admittedly successful) proprietary video game developers.
* **Request relevance.**  Users routinely ask for features without any idea of how they fit into the bigger project.
* **Impossible to please.**  Emotional strings.  Did you really complete that feature sufficiently to make the donors happy?

Let's look at some of the various tools out there.

* Gittip.  Pros: no strings, no requests.  You get freedom.  Cons: it is a trickle.  The median user gets around $20/week.  At one hour of work per week you will never have a chance to really get into the flow.  Promotion is hard due to the slow and disconnected nature.

* Feature funding.  Bountysource and funding.openinitiative.com.  Pros: you know what the users want.  Cons: Hard to promote.  Donations are broken up across many features, diffusing everything.  You'll get a lump (eventually) but it might be a while and you have to use it on that one feature.  If the features are user-generated, there may be some disconnect.  If there is scope creep or you poorly estimate how hard something is, then no one is happy with the results.

* Crowd funding.  Kickstarter and IndieGoGo.  This is one of my favorites.  Marketing is important, but singular events easier to inform people of.  You get a lump sum, which means you can allocate a solid lump of time.  Downside is the incentives.  The two most common incentives are *secrets* and *vanity*.  Secrets would be any sort of private mailing list, private repository or early access.  These are not at all in the spirit of FOSS.  Why should acting proprietary be a reward?  Vanity is a little more subtle.  Unless a dev is a BDFL, they typically get no recognition.  Until they screw up.  Then their name is everywhere.  The developers are generally low-key people and so are most of the users.  The majority of donations to most projects are anonymous, for example.  People generally don't want their name on things, so it is not a good perk.

Why Featuritis
==============

Featuritis is designed to combine the one nice part about feature funding (knowledge of what people want) with all the good parts of crowd funding.  People love to request features, so after donating they can vote on which features are most important to them.  They can vote for any number of features and can change their votes at any time.  The developers can arrange these goals into hierarchies of requirements, so donors can better understand the magnitude of a task and where development time is being spent.  Obviously a developer should spend most of their time working on the most popular features, but this is not a hard requirement as with feature-funding.

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

### `new`

Provide the title of a task, it will create an empty task and return the task id.

### `doing`

Set yourself on that task's activity list.  Can also set other devs.  You can only do one task at a time.

### `finished`

Mark a task as completed.  Requires a commit URL.

### `star`

Increase or decrease the number of stars on a task.  This supersedes the vote count and is meant for Very Important Tasks.

### `task`

Edit the attributes of a task.  Subcommands include

* `show` to report info
* `childof / c` to to add a requirement link
* `parentof / p` to add a dependency link
* `remove` to clear a link

### `comment`

Edit the description of a task.  Comments are a list of strings, each element gets its own line on the summary page.  Subcommands include list editing like `append` `insert` `remove` and `swap`.

### `admin`

A bit more complicated and messy.  Mostly used for registering voters.  Dig the source.

Developer notes
===============

The same code base supports both Python2 and Python3.

Launch the bot with `python featuritis.py example.conf` though you should probably read and tweak the conf file first.

Superficially it would appear that tasks can form trees.  In fact the engine can handle generic cyclic graphs.  So if the tree walking code looks like weird paranoid overkill, this is why.

Basic identification services such as passwords appear to be completely missing.  This job is handed off to the IRC server's NickServ instead.  There are also no automatic user registration services.  This is done by manually by admin commands.

The entire bot is built in the [crash-only](https://www.usenix.org/legacy/events/hotos03/tech/full_papers/candea/candea_html/index.html) style.  As such, there is no disk-backed database.  Instead there is an append-only log file that essentially logs all commands sent to the bot.  At start up, these commands are fed through the exact same code paths as the IRC parsers.  This rebuilds the internal data structures.

The append-only log also makes it very easy to roll back to any point in time.  Other bots I've done in this style have used it for infinite arbitrary undo, though Featuritis is unlikely to get that option.

Probably the weirdest part of the code is the split between `featuritis.py` (the frontend) and `feature_backend.py`.  The frontend contains all the basic data structures and mutable state.  The IRC library and internal DB are both in the frontend.  The backend (which is about five times larger) contains all the methods and functions.  By splitting the data and functions, the functions can be tweaked, reloaded and updated at runtime with ease.  You almost never need to shutdown and restart the bot while working on it.  And if the reload fails, it'll tell you as such and keep on using the older version.

