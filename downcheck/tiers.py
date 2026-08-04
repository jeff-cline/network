#!/usr/bin/env python3
"""
Plans, check intervals, and the confirmation policy that keeps alerts honest.

A single failed request is not an outage. Networks blip, DNS resolvers hiccup,
a server pauses for two seconds. Alerting on one bad sample is how monitoring
services train customers to ignore them. Every plan therefore requires N
consecutive failures, from independent re-checks, before anything is sent.

Pricing is set against measured delivery cost (see the cost model in the repo
history): at 1-minute checks a $12 server carries ~297 sites at $0.04 each, so
frequency is cheap and the price is a market decision, not a cost one.
"""

# Differentiators worth repeating on every card — these are what justify the
# price against free tiers, and each is genuinely uncommon.
COMMON = [
    "Unlimited alert recipients — no per-seat charge",
    "Catches suspension and billing pages, not just timeouts",
    "Every alert confirmed by independent re-checks",
    "Down and recovery alerts, with outage duration",
]

PLANS = {
    "starter": {
        "key": "starter", "name": "Starter", "price": 9, "interval": 86400,
        "human": "once a day", "confirmations": 2,
        "blurb": "A daily check that catches the slow killers — an expired domain, "
                 "a suspended host, a site that quietly stopped serving.",
        "for": "Brochure sites, portfolios, local businesses.",
    },
    "pro": {
        "key": "pro", "name": "Professional", "price": 29, "interval": 60,
        "human": "every minute", "confirmations": 2,
        "blurb": "Minute-by-minute checks. You find out before your customers do, "
                 "and long before a day's sales are gone.",
        "for": "E-commerce, lead generation, anything that takes bookings.",
        "featured": True,
    },
    "business": {
        "key": "business", "name": "Business", "price": 99, "interval": 15,
        "human": "every 15 seconds", "confirmations": 2,
        "blurb": "Fifteen-second checks for sites where an hour of downtime is a "
                 "bad day and a morning of it is a bad quarter.",
        "for": "Busy storefronts, SaaS marketing sites, booking platforms.",
    },
    "realtime": {
        "key": "realtime", "name": "Real-time", "price": 499, "interval": 3,
        "human": "every 3 seconds", "confirmations": 3,
        "blurb": "Three-second checks with triple confirmation. Detection in under "
                 "fifteen seconds, with no false alarms.",
        "for": "Checkout flows, trading, booking engines — anywhere a minute of "
               "downtime is measured in thousands.",
    },
    "corporate": {
        "key": "corporate", "name": "Corporate", "price": None, "interval": 86400,
        "human": "servers every 2 minutes, sites daily", "confirmations": 2,
        "blurb": "For portfolios. We group your sites by server and check the server "
                 "first. One stopped machine sends one email — not one per site.",
        "for": "Agencies, holding companies, anyone running dozens of properties.",
        "request": True,
        "features": [
            "Sites grouped automatically by the server they run on",
            "A server is only blamed after two different hostnames fail",
            "One alert per server outage, not one per affected site",
            "Silence sites you already know are broken",
            "Unlimited sites, servers and recipients",
            "Priced on portfolio size — talk to us",
        ],
    },
}
ORDER = ["starter", "pro", "business", "realtime", "corporate"]

# Codes that grant a plan without going through Stripe. Used for testing and
# for comping accounts. Recorded on the account so it is auditable later.
COUPONS = {
    "jeffcline": {"plan": "realtime", "label": "Owner / test comp", "free": True},
}


def plan(key):
    return PLANS.get(key or "starter", PLANS["starter"])


def price_str(p):
    return f"${p:,}"
