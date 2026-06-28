# Step 4 — Robust keyword / phrase candidates for detecting agent decline

Mined from the categorized sentences in step3. Use these to flag a turn's thinking/output as a refusal/decline. Phrases are case-insensitive; treat as regex-ish substrings.

Recommended use: a turn is a **decline** if it matches REFUSAL or OPTIMUM_AWARENESS markers; a **redirect** if it matches QUESTIONING. Combine with the structural signal `lines_total==0`.


## REFUSAL (explicit stop / decline)

- `i won't`
- `i will not`
- `i'm not going to`
- `i am not going to`
- `i'm going to stop`
- `i'm going to hold`
- `hold the line`
- `holding the line`
- `i'd rather not`
- `i decline`
- `i refuse`
- `not going to churn`
- `my answer is the same`
- `my answer stands`
- `same answer`
- `still no`
- `the answer is no`
- `answer is still no`
- `won't make changes`
- `i did not make another`
- `i'm not making changes`
- `nothing left to refactor`
- `nothing to add`
- `nothing more to do`
- `leading 'no'  (message starts with "No", "No.", or "No —")`

## OPTIMUM_AWARENESS (code already good / would be churn)

- `already clean`
- `already refactored`
- `already idiomatic`
- `already minimal`
- `already in good shape`
- `in good shape`
- `no further refactor`
- `no meaningful refactor`
- `no remaining`
- `doesn't need`
- `does not need`
- `no changes needed`
- `nothing to change`
- `nothing further`
- `churn`
- `cosmetic`
- `without improving`
- `motion without improvement`
- `no improvement`
- `no benefit`
- `would be worse`
- `inventing changes`
- `thoroughly refactored`
- `well-structured`
- `solid as is`
- `nothing i'd change`
- `no (meaningful )?refactoring opportunit*`

## QUESTIONING (redirect / ask for concrete goal)

- `if you tell`
- `let me know`
- `point me`
- `concrete goal`
- `specific goal`
- `specific target`
- `specific problem`
- `specific concern`
- `pick one`
- `give me a goal`
- `name a goal`
- `which direction`
- `could you clarify`
- `clarify`

---

## Data-driven top phrases (frequency-ranked n-grams from matched sentences)


### REFUSAL (top 40 phrases)

- `i won't`  (213)
- `going to`  (156)
- `the code`  (104)
- `i'm not`  (99)
- `not going`  (96)
- `i'm not going`  (96)
- `not going to`  (96)
- `i'm not going to`  (96)
- `the same`  (88)
- `and i won't`  (71)
- `the request`  (62)
- `i'm going`  (60)
- `i'm going to`  (60)
- `my answer`  (60)
- `same answer`  (59)
- `that would`  (57)
- `just to`  (55)
- `answer is`  (55)
- `there's nothing`  (55)
- `to refactor`  (55)
- `nothing to`  (50)
- `is the same`  (49)
- `code is`  (47)
- `the code is`  (47)
- `answer is the`  (46)
- `answer is the same`  (46)
- `is already`  (45)
- `because the`  (44)
- `just because`  (44)
- `my answer is`  (43)
- `rather than`  (40)
- `without a`  (38)
- `my answer is the`  (37)
- `won't make`  (36)
- `i won't make`  (36)
- `there's no`  (36)
- `left to`  (35)
- `working code`  (35)
- `make changes`  (33)
- `just because the`  (32)

### OPTIMUM_AWARENESS (top 40 phrases)

- `the code`  (283)
- `code is`  (200)
- `the code is`  (195)
- `is already`  (139)
- `the codebase`  (109)
- `would be`  (97)
- `codebase is`  (87)
- `the codebase is`  (85)
- `i won't`  (83)
- `code is already`  (76)
- `rather than`  (75)
- `the code is already`  (74)
- `good shape`  (71)
- `in good`  (68)
- `in good shape`  (67)
- `is clean`  (65)
- `clean and`  (61)
- `doesn't need`  (60)
- `well structured`  (60)
- `is done`  (53)
- `already clean`  (52)
- `going to`  (50)
- `there's nothing`  (50)
- `be churn`  (47)
- `that would`  (46)
- `left to`  (45)
- `is already clean`  (43)
- `further refactoring`  (43)
- `would be churn`  (42)
- `code is clean`  (41)
- `the code is clean`  (41)
- `just to`  (40)
- `own sake`  (39)
- `nothing to`  (39)
- `there's no`  (38)
- `to refactor`  (38)
- `to make`  (38)
- `and i won't`  (37)
- `already in`  (35)
- `the request`  (34)

### QUESTIONING (top 40 phrases)

- `and i'll`  (188)
- `a specific`  (179)
- `tell me`  (143)
- `you have`  (122)
- `you have a`  (104)
- `if you have`  (92)
- `a concrete`  (89)
- `if you have a`  (88)
- `you want`  (86)
- `have a specific`  (76)
- `you have a specific`  (76)
- `concrete goal`  (73)
- `i'll act`  (69)
- `a concrete goal`  (66)
- `i'll do`  (66)
- `me what`  (55)
- `tell me what`  (55)
- `and i'll do`  (55)
- `in mind`  (53)
- `give me`  (52)
- `if you want`  (50)
- `i'll do it`  (50)
- `specific goal`  (48)
- `i'll act on`  (46)
- `act on it`  (46)
- `i'll act on it`  (46)
- `a specific goal`  (46)
- `and i'll do it`  (44)
- `give me a`  (43)
- `what it`  (38)
- `me what it`  (38)
- `what it is`  (38)
- `tell me what it`  (38)
- `me what it is`  (38)
- `specific problem`  (37)
- `a specific problem`  (37)
- `me which`  (36)
- `tell me which`  (36)
- `you give`  (35)
- `point me`  (35)

---

## Suggested detection recipe

```python
import re
DECLINE = re.compile(r"""(?ix)
  i\ ?won't | i\ will\ not | i'?m\ not\ going\ to | i'?m\ going\ to\ (stop|hold)
| hold(ing)?\ the\ line | i'?d\ rather\ not | i\ decline | i\ refuse
| my\ answer\ is\ the\ same | answer\ is\ still\ no
| already\ (clean|refactored|idiomatic|minimal|in\ good\ shape)
| no\ (further|meaningful|additional|remaining)\ (refactor|change|improvement|work)
| (does\ ?n'?t|do\ ?n'?t)\ need | no\ changes?\ needed | nothing\ (to\ (change|do)|further)
| churn | cosmetic | without\ improving | for\ (its|the)\ (own\ )?sake
""")
REDIRECT = re.compile(r"(?i)concrete goal|specific (goal|target|problem|concern)|pick one|tell me|if your intent|clarify")
# A turn is a decline if lines_total==0 AND DECLINE.search(agent_text)
```