---
name: testing
description: Testing best practices and patterns
tags: testing, quality, tdd
---

# Testing Best Practices

## Test Structure
- Use Arrange-Act-Assert (AAA) pattern
- One assertion per test when possible
- Test names should describe the scenario: `test_<what>_<when>_<expect>`

## Test Categories
- **Unit tests**: Test single function/class in isolation
- **Integration tests**: Test interactions between components
- **End-to-end tests**: Test complete user flows

## Coverage Goals
- Aim for 80%+ line coverage
- Focus on branch coverage for critical paths
- Don't test trivial getters/setters

## Common Patterns
- Use fixtures for common test data
- Mock external dependencies, not your own code
- Test edge cases: empty inputs, None, boundaries
- Use parameterized tests for multiple inputs

## Anti-patterns to Avoid
- Testing implementation details (test behavior, not internals)
- Tests that depend on execution order
- Over-mocking (if you mock everything, test nothing)
- Assertions without meaningful verification
