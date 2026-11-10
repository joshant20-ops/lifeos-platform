# Personal Finance F1

F1 replaces the spreadsheet's core pot-allocation workflow without importing private spreadsheet data into GitHub.

Input authority for spending is the owner's manually entered Monzo category totals. Monzo transaction-level categorisation is not duplicated. The local application stores immutable events and derives virtual pot balances, inter-pot obligations and goal progress.

The personal budgeting event store is intentionally separate from the existing Finance rental/accounting read model. The latter remains read-only and retains its formal-accounting authority boundary.

## Local workflow

1. Create pots and optional targets/monthly budget amounts.
2. Map Monzo category names to pots.
3. Enter a month and Monzo category spending total.
4. Unknown categories stop for mapping/review.
5. Duplicate month/category submissions fail rather than double count.
6. Add allocations, transfers, loans, repayments and refunds separately.
7. Dashboard derives current usable balance, receivables, debts, net position and goal progress.

The web service has no cloud dependency. Production financial values must remain local. GitHub and CI use synthetic values only.

The supplied Compose binds the service to loopback port 18080 by default so exposure must be an explicit local reverse-proxy decision.
