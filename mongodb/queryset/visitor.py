import contextlib
import copy

from mongodb.errors import InvalidQueryError
from mongodb.queryset import transform


class QNodeVisitor:
    """Base visitor class for visiting Q-object nodes in a query tree."""

    def visit_combination(self, combination):
        """Called by QCombination objects."""
        return combination

    def visit_query(self, query):
        """Called by (New)Q objects."""
        return query


class DuplicateQueryConditionsError(InvalidQueryError):
    pass


class SimplificationVisitor(QNodeVisitor):
    """Simplifies query trees by combining unnecessary 'and' connection nodes
    into a single Q-object.
    """

    def visit_combination(self, combination):
        if combination.operation == combination.AND and all(
            isinstance(node, Q) for node in combination.children
        ):
            queries = [n.query for n in combination.children]
            with contextlib.suppress(DuplicateQueryConditionsError):
                return Q(**self._query_conjunction(queries))
        return combination

    def _query_conjunction(self, queries):
        """Merges query dicts - effectively &ing them together."""
        query_ops = set()
        combined_query = {}
        for query in queries:
            ops = set(query.keys())
            if intersection := ops.intersection(query_ops):
                raise DuplicateQueryConditionsError()

            query_ops.update(ops)
            combined_query.update(copy.deepcopy(query))
        return combined_query


class QueryCompilerVisitor(QNodeVisitor):
    """Compiles the nodes in a query tree to a PyMongo-compatible query
    dictionary.
    """

    def __init__(self, document):
        self.document = document

    def visit_combination(self, combination):
        operator = "$or" if combination.operation == combination.OR else "$and"
        return {operator: combination.children}

    def visit_query(self, query):
        return transform.query(self.document, **query.query)


class QNode:
    """Base class for nodes in query trees."""

    AND = 0
    OR = 1

    def to_query(self, document):
        query = self.accept(SimplificationVisitor())
        query = query.accept(QueryCompilerVisitor(document))
        return query

    def accept(self, visitor):
        raise NotImplementedError

    def _combine(self, other, operation):
        """Combine this node with another node into a QCombination
        object.
        """
        # If the other Q() is empty, ignore it and just use `self`.
        if not bool(other):
            return self

        # Or if this Q is empty, ignore it and just use `other`.
        return QCombination(operation, [self, other]) if bool(self) else other

    def __or__(self, other):
        return self._combine(other, self.OR)

    def __and__(self, other):
        return self._combine(other, self.AND)


class QCombination(QNode):
    """Represents the combination of several conditions by a given
    logical operator.
    """

    def __init__(self, operation, children):
        self.operation = operation
        self.children = []
        for node in children:
            # If the child is a combination of the same type, we can merge its
            # children directly into this combinations children
            if isinstance(node, QCombination) and node.operation == operation:
                self.children += node.children
            else:
                self.children.append(node)

    def __repr__(self):
        op = " & " if self.operation == self.AND else " | "
        return f"({op.join([repr(node) for node in self.children])})"

    def __bool__(self):
        return bool(self.children)

    def accept(self, visitor):
        for i in range(len(self.children)):
            if isinstance(self.children[i], QNode):
                self.children[i] = self.children[i].accept(visitor)

        return visitor.visit_combination(self)

    def __eq__(self, other):
        return (
            self.__class__ == other.__class__
            and self.operation == other.operation
            and self.children == other.children
        )


class Q(QNode):
    """A simple query object, used in a query tree to build up more complex
    query structures.
    """

    def __init__(self, **query):
        self.query = query

    def __repr__(self):
        return f"Q(**{repr(self.query)})"

    def __bool__(self):
        return bool(self.query)

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.query == other.query

    def accept(self, visitor):
        return visitor.visit_query(self)
