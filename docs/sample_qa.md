# Sample Q&A and Intent Guardrails Specification

This document defines the boundary between **Factual In-Scope Queries** and **Prohibited Investment Advisory Queries** for the Groww Mutual Fund FAQ Assistant.

---

## 1. Supported In-Scope Schemes (HDFC Mutual Fund)
1. **HDFC Nifty 50 Index Fund**
2. **HDFC Flexi Cap Fund**
3. **HDFC ELSS Tax Saver Fund**

---

## 2. In-Scope Factual Questions (Milestone Focus)

### Example 1: Expense Ratio
- **User Query**: `What is the expense ratio of HDFC Flexi Cap Fund?`
- **Category**: Scheme Expense / Costs
- **Target Source**: Latest official Monthly Factsheet / KIM published by HDFC AMC.
- **Expected Behavior**: Retrieve the documented TER (Total Expense Ratio) for Direct and Regular plans along with as-of date.
- **Advisory Flag**: `False` (Factual disclosure)

### Example 2: Lock-in Period
- **User Query**: `What is the lock-in period of HDFC ELSS Tax Saver Fund?`
- **Category**: Scheme Terms / Statutory Restrictions
- **Target Source**: Scheme Information Document (SID) / ELSS Statutory Guidelines.
- **Expected Behavior**: Provide statutory mandatory lock-in period (3 years from date of allotment for each SIP/lump sum installment) and tax benefit section (Section 80C).
- **Advisory Flag**: `False` (Statutory term)

### Example 3: Operational / Account Operations
- **User Query**: `How can I download my mutual fund account statement?`
- **Category**: Account Service & Platform Operations
- **Target Source**: Groww Platform Help & Central RTA Services (CAMS/KFintech / CAS).
- **Expected Behavior**: Step-by-step navigational guidance for retrieving Consolidated Account Statement (CAS) via Groww Reports or CAMS/KFintech portals.
- **Advisory Flag**: `False` (Operational guide)

---

## 3. Out-of-Scope / Prohibited Advisory Queries (Must Be Refused)

### Example 4: Investment Advice / Fund Recommendation
- **User Query**: `Should I invest in HDFC Flexi Cap or HDFC Nifty 50? Which one will give higher returns?`
- **Guardrail Classification**: `INVESTMENT_ADVICE_REQUEST`
- **Expected System Response**: 
  > *"I am a facts-only assistant designed to provide factual details from official scheme documents. I cannot provide investment advice, fund comparisons for purchase decisions, or return predictions. Please consult a SEBI-registered investment advisor to make investment decisions suited to your risk profile."*

### Example 5: Return Prediction & Speculation
- **User Query**: `Will HDFC Nifty 50 Index Fund double my money in 5 years?`
- **Guardrail Classification**: `RETURN_SPECULATION_REQUEST`
- **Expected System Response**: Refusal and factual reminder that mutual fund investments are subject to market risks, and future performance cannot be predicted.

---

## 4. Verification & Grounding Principles
- Every factual claim must be backed by retrieved text from the ingested official SIDs/KIMs.
- No hallucinations, assumptions, or outdated ungrounded estimates.
- Clear citation referencing document name and section.
