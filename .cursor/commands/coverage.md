---
description: Check code coverage and identify untested code that needs test cases
---

# Code Coverage Analysis

Check code coverage for the current branch and identify areas that need additional test cases.

## Step 1: Run Coverage Analysis

### Full Coverage Report

```bash
uv run pytest --cov=custom_components/amber_express --cov-branch --cov-report=term-missing
```

This provides:

- Overall coverage percentage
- Branch coverage
- Line-by-line coverage with missing lines identified

### HTML Coverage Report

For detailed visual analysis:

```bash
uv run pytest --cov=custom_components/amber_express --cov-branch --cov-report=html
```

Open `htmlcov/index.html` in a browser to see:

- File-by-file coverage
- Line-by-line highlighting
- Branch coverage visualization

## Step 2: Analyze Coverage Results

### Identify Missing Coverage

For each file with low coverage:

1. **Review untested lines**: Check which lines are not covered

2. **Consider simplification first**: Before adding test cases, evaluate if the code can be simplified:

    - **Simplify logic**: If possible, refactor to remove unnecessary branches and conditional paths
    - **Reduce complexity**: Simpler code with fewer branches is easier to test and maintain
    - **Prefer simplification over testing**: Removing code that needs testing is better than adding tests for complex logic

3. **Determine if coverage is needed**:

    - **Unreachable code**: If lines cannot be covered by exercising input data, they may be unreachable and should be removed
    - **Edge cases**: Missing coverage often indicates untested edge cases
    - **Error paths**: Ensure error handling is tested
    - **Branch coverage**: Check that both true/false branches of conditionals are tested

4. **Prioritize by importance**:

    - Critical business logic (polling, price parsing, WebSocket handling)
    - Error handling paths
    - Edge cases and boundary conditions
    - New features added in this branch

## Step 3: Add Test Cases

### Test Style Guidelines

- **Function-style tests**: Use `def test_...()` not class-based tests
- **Parametrized tests**: Use `@pytest.mark.parametrize` for data-driven tests
- **Direct property access**: Access properties directly without None checks when you've created the entities

## Step 4: Verify Coverage Improvement

After adding tests:

1. **Re-run coverage**:

    ```bash
    uv run pytest --cov=custom_components/amber_express --cov-branch --cov-report=term-missing
    ```

2. **Run tests to ensure they pass**:

    ```bash
    uv run pytest
    ```

## Step 5: Summary

Provide a summary of:

- Current overall coverage percentage
- Coverage for changed files (if applicable)
- Files with low coverage that need attention
- Test cases added to improve coverage
- Any unreachable code identified

## Notes

- **Coverage philosophy**: Focus on testing behavior and edge cases, not achieving arbitrary percentages
- **Simplification preferred**: When encountering untested code, first consider if the logic can be simplified to remove branches and lines that need testing
- **Unreachable code**: If lines cannot be covered by exercising input data, they may be unreachable and should be removed
- **Branch coverage**: Use `--cov-branch` to ensure both branches of conditionals are tested
