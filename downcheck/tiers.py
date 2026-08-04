#!/usr/bin/env python3
"""
Plans, check intervals, and the confirmation policy that keeps alerts honest.

A single failed request is not an outage. Networks blip, DNS resolvers hiccup,
a server GCs for two seconds. Alerting on one bad sample is how monitoring
services train customers to ignore them. Every plan therefore requires N
consecutive failures, from a re-check, before anything is sent.
"""

PLANS = {
    "starter": {
        "key": "starter", "name": "Starter", "price": 9, "interval": 86400,
        "human": "once a day",
        "confirmations": 2,
        "blurb": "A daily check that catches the slow killers — an expired domain, "
                 "a suspended host, a site that quietly stopped serving.",
        "for": "Brochure sites, portfolios, local businesses.",
    },
    "pro": {
        "key": "pro", "name": "Professional", "price": 99, "interval": 300,
        "human": "every 5 minutes",
        "confirmations": 2,
        "blurb": "Five-minute checks. You find out before your customers do, "
                 "and long before a day's sales are gone.",
        "for": "E-commerce, lead generation, anything that takes bookings.",
    },
    "realtime": {
        "key": "realtime", "name": "Real-time", "price": 499, "interval": 3,
        "human": "every 3 seconds",
        "confirmations": 3,
        "blurb": "Three-second checks with triple confirmation. Detection in "
                 "under fifteen seconds, with no false alarms.",
        "for": "Checkout flows, trading, booking engines, anything where a "
               "minute of downtime is measured in thousands.",
    },
}
ORDER = ["starter", "pro", "realtime"]

# Codes that grant a plan without going through Stripe. Used for testing and
# for comping accounts. Recorded on the account so it is auditable later.
COUPONS = {
    "jeffcline": {"plan": "realtime", "label": "Owner / test comp", "free": True},
}


def plan(key):
    return PLANS.get(key or "starter", PLANS["starter"])


def price_str(p):
    return f"${p:,}"
