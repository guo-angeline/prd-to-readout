# PRD: One-Tap Checkout

## Problem
Shoppers abandon their carts on the payment step. The current flow takes four
screens and re-asks for shipping and payment details we already have on file.

## Proposal
Add a "One-Tap Checkout" button on the cart screen for returning customers with
a saved card and address. Tapping it places the order immediately with a 5-second
undo window, skipping the multi-screen flow entirely.

## Goal
Increase the share of carts that convert to completed orders, without increasing
the rate of order cancellations or support tickets about accidental purchases.

## Target users
Returning customers with at least one saved payment method.

## Success looks like
More carts turn into paid orders. We are willing to ship if conversion improves
and cancellations do not get meaningfully worse.

## Approvers
- Product / metrics owner: @octocat
- Engineering (logging): @hubot
- Data Science (QA + SQL): @octocat
