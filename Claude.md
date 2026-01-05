# Coding Style Instructions

## Overview

Follow these patterns for consistent, maintainable Python code using
Domain-Driven Design and Clean Architecture principles. This guide emphasizes
principles over patterns, leading from foundational thinking down to specific
implementation details.

## Design Philosophy and Principles

### Core Development Philosophy

**Software Design is About Managing Complexity**
The primary challenge in software development is not writing code that works,
but writing code that remains comprehensible, maintainable, and adaptable
as systems grow and change.

**Principles Over Patterns**
While design patterns are useful tools, understanding the underlying principles
is more valuable. Principles guide you toward good solutions; patterns are
specific implementations that may or may not fit your context.

### Fundamental Design Principles

#### 1. Clarity and Intent

- Code should express business intent clearly
- Optimize for readability and understanding
- Choose explicit over implicit when it aids comprehension
- Do not use relative imports

#### 2. Separation of Concerns

- Each component should have a single, well-defined responsibility
- Changes to one concern shouldn't ripple through unrelated areas
- Design boundaries that align with business concepts

#### 3. Dependency Inversion

- Depend on abstractions, not implementations
- Inject dependencies rather than creating them
- Design for testability from the beginning

#### 4. Evolutionary Design

- Build systems that can adapt to changing requirements
- Prefer composition and configuration over inheritance
- Design for extension without modification

#### 5. Testing

- Write tests that verify behaviour, not implementation: Focus on *what* the
  system should do, not *how* it does it
- Arrange-Act-Assert: Clear three-phase structure
- One Behaviour Per Test: Each test should verify a single behaviour
- Descriptive Names: Test names should explain the expected behaviour
- Prefer PyTest where possible and use parameterize to reduce number of
  individual tests needed

### Decision-Making Framework

When facing design decisions, ask:

1. **Does this increase or decrease complexity?**
2. **Will this be easy to change when requirements evolve?**
3. **Can I test this behaviour in isolation?**
4. **Does this express the business intent clearly?**
5. **Am I introducing unnecessary coupling?**

### Common Anti-Patterns to Avoid

- **Premature Optimization**: Focus on clear design first
- **God Objects**: Classes that know or do too much
- **Feature Envy**: Objects that access other objects' data excessively
- **Primitive Obsession**: Using basic types instead of domain objects
- **Tight Coupling**: Dependencies that are hard to substitute or test

## Core Design Principles in Practice

### Single Responsibility Principle (SRP)

**Core Principle:**
Each class or function should have one reason to change. We should be able to
describe what a component does without using "and" or "or".

**Identifying Responsibilities:**

- **Data vs. Behaviour**: Separate what something *is* from what it *does*
- **Change Triggers**: If different business requirements would modify
  the same code, split the responsibilities
- **Stakeholder Concerns**: Different stakeholders caring about different
  aspects suggests multiple responsibilities
- **Abstraction Levels**: Mixing high-level orchestration with low-level
  details violates SRP

**SRP in Practice**

Instead of a monolithic component that handles multiple concerns, separate each responsibility:

```python
# Violates SRP - too many responsibilities
class OrderProcessor:
    def process(self, order_data: dict) -> bool:
        # Validation logic
        if not order_data.get('customer_id'):
            return False
        
        # Business calculation
        total = sum(item['price'] for item in order_data['items'])
        
        # Database persistence
        self.db.save_order(order_data)
        
        # External notification
        self.email_service.send_confirmation(order_data['customer_id'])
```

Apply SRP by separating concerns.

### Composition Over Inheritance

**Core Principle:**
Favour object composition over class inheritance. Inheritance creates tight
coupling and rigid hierarchies; composition provides flexibility and
better encapsulation.

- **Runtime Flexibility**: Change behaviour by injecting different objects
- **Multiple Behaviours**: Combine any number of behaviours without
  inheritance complexity
- **Easier Testing**: Mock individual components rather than class
  hierarchies
- **Clearer Intent**: Dependencies are explicit in constructors

**When to Still Use Inheritance:**

- **True "is-a" Relationships**: When subclass is genuinely a specialized
  version of the parent
- **Template Method Pattern**: When you need to enforce a specific
  algorithm structure
- **Framework Extensions**: When extending abstract base classes or
  protocols

### Dependency Inversion & Injection

**Core Principle: Invert Dependencies**
Don't create dependencies inside classes; inject them from outside. This
enables flexibility, testability, and adherence to the Open/Closed Principle.

**Benefits:**

- **Testability**: Easy to substitute test doubles for real dependencies
- **Flexibility**: Swap implementations without changing business logic
- **Configuration**: Assemble different object graphs for different environments
- **Single Responsibility**: Classes focus on their core logic, not dependency management

**Encapsulation Principles:**

- **Hide Implementation Details**: Expose only what clients need to know
- **Control Access**: Use properties and methods to manage state changes
- **Maintain Invariants**: Ensure objects remain in valid states
- **Minimize Surface Area**: Smaller public APIs are easier to maintain

### Code Clarity and Readability

**Principle: Code is Read More Often Than Written**
Optimize for the reader, not the writer. Code should communicate intent
clearly without requiring deep analysis.

**Naming Principles:**

- **Intention-Revealing**: Names should answer why it exists, what it does,
  and how it's used
- **Avoid Mental Mapping**: Don't make readers translate abbreviations or
  codes
- **Use Domain Language**: Speak the language of the business domain
- **Consistent Vocabulary**: One concept, one word throughout the codebase

```python
# Poor naming - requires mental translation
def calc(d: float, r: float) -> float:
    return d * r * 365

# Clear naming - intention is obvious
def calculate_annual_interest(principal: float, daily_rate: float) -> float:
    return principal * daily_rate * 365
```

**Function Design for Clarity:**

- **Do One Thing**: Functions should have a single, clear purpose
- **Small and Focused**: If you need scrolling to see the whole function,
  it's probably too long
- **Command-Query Separation**: Functions either do something or return
  something, not both
- **Error Handling**: Use exceptions for exceptional cases, not control flow

**Class Design for Understanding:**

- **Tell, Don't Ask**: Objects should control their own state rather than
  exposing it for manipulation
- **Immutability When Possible**: Immutable objects are easier to reason about
- **Progressive Disclosure**: Show only what's necessary at each abstraction
  level

## Clean Architecture

### Architectural Principles

**Dependency Rule**: Dependencies should point inward toward the domain.
Outer layers can depend on inner layers, but inner layers should never
depend on outer layers.

### Recommended Project Structure

When building Web services, favour DDD patterns

```text
├── [web service name]/
│   ├── domain_models/          
│   ├── services/
│   │   ├── application/
│   │   └── domain/
│   ├── infrastructure/   # External integrations
```

**Key Guidelines:**

- Organize by feature/domain, not by technical patterns
- Interfaces for objects like repositories may be defined in domain,
  implemented in infrastructure. Use best judgement
- Application service orchestrates use cases without business logic.
  REST/MCP controllers fit in application layer

## Implementation Guidelines

### Modern Python Guidelines

**Type System as Design Tool**
Use Python's type system to make invalid states unrepresentable and to
communicate your design intent.

#### Embrace Functional Concepts

- Immutability reduces complexity
- Pure functions are easier to test and reason about
- Composition creates flexible, reusable components

**Framework-Agnostic Design**
Design your core domain logic independently of frameworks. Frameworks should
be implementation details, not architectural drivers.

### Type Hints & Documentation

**Type Annotation Principles:**

- **Clarity**: Types should communicate intent, not just satisfy the
  type checker
- **Simplicity**: Use built-in types (`list`, `dict`, `set`) over
  `typing` module when possible
- **Expressiveness**: Union types (`str | int`) are more readable than
  `Union[str, int]`
- **Documentation**: Type hints are part of your API contract - make
  them meaningful

**Documentation Style:**
Use Sphinx-style docstrings for consistency with Python documentation tools:

```python
def calculate_tax(amount: Money, rate: float) -> Money:
    """Calculate tax on a monetary amount.
    
    :param amount: The base amount to calculate tax on
    :param rate: Tax rate as a decimal (0.1 for 10%)
    :return: Tax amount in the same currency as the base amount
    :raises ValueError: If rate is negative
    """
```

### Functions vs Classes

**Use Functions When:**

- Operation is stateless
- Single transformation or calculation
- No need to maintain internal state

**Use Classes When:**

- Need to maintain state between calls
- Grouping related functionality
- Implementing domain entities or services
