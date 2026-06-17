---
name: code-review
description: Review code for bugs, style issues, and best practices
tags: quality, review, best-practices
---

# Code Review Checklist

## Critical Issues (Must Fix)
- Security vulnerabilities (SQL injection, XSS, hardcoded secrets)
- Race conditions and thread safety issues
- Memory leaks and resource cleanup
- Error handling for edge cases

## Important Issues (Should Fix)
- Performance bottlenecks (N+1 queries, unnecessary loops)
- Incorrect or missing type hints
- Violations of SOLID principles
- Hardcoded values that should be constants or config

## Style Issues (Nice to Fix)
- Inconsistent naming conventions
- Missing or outdated comments
- Functions that are too long (>50 lines)
- Magic numbers without explanation

## Review Process
1. Read the entire change to understand intent
2. Check each file for the above issues
3. Provide specific line references when possible
4. Suggest concrete fixes, not just problems
5. Distinguish between blocking and non-blocking feedback
