# §1 Counting

Counting asks how many objects fit a description. It builds on nothing earlier, and [§2 Graphs](#sec-2) uses it to count edges.

## 1.1 Sums of a range {#sec-1-sums}

The **sum of the first n integers** is \(\frac{n(n+1)}{2}\) [D1 p.4]. Pairing the first term with the last gives

\[ \sum_{i=1}^{n} i = \frac{n(n+1)}{2}. \]

A **range** is every integer from a to b, inclusive [D1 p.3].

To sum a range:

Step 1: Count its terms: \(b - a + 1\).
Step 2: Add the first and the last term.
Step 3: Multiply the two and halve the product.

> **Worked example 1.1: Summing 3 to 7** {#ex-1-range}
> Setup: the range 3 to 7.
> Step 1: 5 terms.
> Step 2: \(3 + 7 = 10\).
> Step 3: \(5 \times 10 / 2 = 25\).
> **Result:** 25.
> **Conclusion:** the pairing rule needs only the count and the two ends.

**How it's tested:** compute a sum and show the pairing. Practice: [HW1 Q1a].

## 1.2 Three counting rules {#sec-1-rules}

- a) **Product:** independent choices multiply [D1 p.6]. {#set-rules-a}
- b) **Sum:** disjoint cases add. {#set-rules-b}
- c) **Bijection:** count an easier set that matches one to one. {#set-rules-c}

Choose the rule by the shape of the description: "and" multiplies ([rule a](#set-rules-a)), "or" adds ([rule b](#set-rules-b)).

| Description | Rule | Count |
| --- | --- | --- |
| a 3-letter code over 26 letters | product | \(26^3 = 17576\) |
| a code of 1 or 2 digits | sum | \(10 + 100 = 110\) |

> **Pitfall:** Adding cases that overlap counts their overlap twice; the sum rule needs *disjoint* cases.

## 1.3 Must know {#sec-1-must-know}

- **Range sum:** \(\frac{n(n+1)}{2}\) ([§1.1](#sec-1-sums))
- **Three rules:** product, sum, bijection ([§1.2](#sec-1-rules))
