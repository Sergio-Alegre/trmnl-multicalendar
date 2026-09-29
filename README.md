# Calendar plugin for TRMNL

A TRMNL plugin that fetches an ICS calendar and display events in a multi-column list format.

![screenshot](sample.jpg)

## Setup
1. At TRMNL, add a new Private Plugin
2. Choose strategy "Webhook", save the Plugin and copy "Webhook URL"
3. Click "Edit Markup" and populate it with the content of `template.html` file in this directory
4. Create `.env` file in this directory with the following content. Edit configuration as needed.
```
TRMNL_TITLE="<title to display in title bar>"
TRMNL_WEBHOOK_URL=<your Webhook URL>
TRMNL_ICS_URL=<your calendar ICS url(s) seperated by a comma (,)>
TRMNL_DAYS=30 # number of days to display
TRMNL_TZ="<your timezone>" # example: America/Los_Angeles
TRMNL_NUMBER_COLUMNS=5
#TRMNL_DATE_FORMAT="%x (%a)" # example:"%Y-%m-%d (%a)"
#TRMNL_TIME_FORMAT="%H:%M"
#TRMNL_UPDATED_AT_FORMAT="%x %X"
#TRMNL_LOCALE="en_US.UTF-8"
```
5. Run `main.py`


## Credits

This project is a fork of [jfsso/trmnl-calendar](https://github.com/jfsso/trmnl-calendar),
released under the MIT License. It has since been developed independently and is not
intended to be merged back upstream.

Main changes from the original:

- Weekly view redesigned to fit the display limits of the TRMNL 7.5" DIY Kit.
- Display logic changed to show the natural calendar week.
- Support for generating separate plugins for the next week and the full month view.

The original copyright notice and license are preserved in [LICENSE](LICENSE).
