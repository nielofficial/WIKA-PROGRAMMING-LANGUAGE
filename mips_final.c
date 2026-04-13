#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdarg.h>
#include <stdint.h>

/* ============================================================
 *  CONSTANTS — limits and sizes used throughout the program
 * ============================================================ */
#define MAX_WORD_LENGTH   100   /* max length of a variable name or number */
#define MAX_TOKENS        200   /* max number of tokens we can store */
#define MAX_VARIABLES     100   /* max number of variables allowed */
#define MAX_KEYWORDS      1     /* number of supported type keywords (int only) */
#define MAX_ERRORS        200   /* max number of errors we can collect */
#define MAX_RUNTIME_INITS 200   /* max number of runtime initializations */
#define BYTES_PER_WORD    8     /* each variable takes 8 bytes in memory */


/* Labels for what kind of token something is */
typedef enum {
    IDENTIFIER,   
    NUMBER,       
    OPERATOR,     
    PUNCTUATION,  
    KEYWORD,      
    UNKNOWN       
} TokenType;

/* A single token: its type, its text, and the line it was found on */
typedef struct {
    TokenType type;
    char      text[MAX_WORD_LENGTH]; /* the actual text, e.g. "int" or "42" */
    int       line_number;
} Token;



/* One entry in the symbol table */
typedef struct {
    char name[MAX_WORD_LENGTH]; /* variable name, e.g. "a" */
    TokenType type;             /* always IDENTIFIER for variables */
    long initial_value;         /* value if initialized with a constant, e.g. int x = 5 */
    int  is_initialized;        /* 1 = has a known constant value, 0 = unknown until runtime */
} Variable;

/* The actual symbol table and how many variables are in it */
Variable symbol_table[MAX_VARIABLES];
int      variable_count = 0;

/* Maps each variable (by index) to the register number currently holding its value.
   -1 means "not loaded into any register yet." */
int variable_register_map[MAX_VARIABLES];

/* Memory offset of each variable from the start of the data section */
long variable_memory_offsets[MAX_VARIABLES];
long next_memory_offset = 0;

/* Calculates where in memory each variable lives (8 bytes apart) */
void compute_memory_offsets() {
    next_memory_offset = 0;
    for (int i = 0; i < variable_count; i++) {
        variable_memory_offsets[i] = next_memory_offset;
        next_memory_offset += BYTES_PER_WORD;
    }
}




Token  all_tokens[MAX_TOKENS];   /* stores every token seen */
int    all_tokens_count = 0;     /* how many tokens stored so far */
int    total_token_count = 0;    /* grand total of all tokens */

/* Counts broken down by type */
int count_identifiers  = 0;
int count_numbers      = 0;
int count_operators    = 0;
int count_punctuations = 0;
int count_keywords     = 0;
int count_unknown      = 0;
int count_empty_stmts  = 0;      /* standalone semicolons like ";;" */



char error_list[MAX_ERRORS][256]; /* stores error message strings */
int  error_count = 0;

/* Adds a formatted error message to the list (like printf but for errors) */
void add_error(const char *format, ...) {
    if (error_count >= MAX_ERRORS) return;

    va_list args;
    va_start(args, format);
    vsnprintf(error_list[error_count], sizeof(error_list[0]), format, args);
    va_end(args);

    error_count++;
}



/* Returns 1 if a variable with the given name already exists in the table */
int variable_exists(const char *name) {
    for (int i = 0; i < variable_count; i++)
        if (strcmp(symbol_table[i].name, name) == 0)
            return 1;
    return 0;
}

/* Adds a variable to the symbol table if it doesn't exist yet.
   Returns the index of the variable (new or existing). */
int add_variable(const char *name, TokenType type) {
    /* If already in table, just return its index */
    for (int i = 0; i < variable_count; i++)
        if (strcmp(symbol_table[i].name, name) == 0)
            return i;

    /* Otherwise add it */
    if (variable_count < MAX_VARIABLES) {
        strncpy(symbol_table[variable_count].name, name, MAX_WORD_LENGTH - 1);
        symbol_table[variable_count].name[MAX_WORD_LENGTH - 1] = '\0';
        symbol_table[variable_count].type           = type;
        symbol_table[variable_count].initial_value  = 0;
        symbol_table[variable_count].is_initialized = 0;
        variable_count++;
        return variable_count - 1;
    }

    return -1; /* table is full */
}


typedef struct ASTNode {
    Token           token;  /* the operator or value at this node */
    struct ASTNode *left;   /* left child */
    struct ASTNode *right;  /* right child */
} ASTNode;

/* Creates a new tree node from a token */
ASTNode* create_tree_node(Token token) {
    ASTNode *node = (ASTNode*)malloc(sizeof(ASTNode));
    node->token = token;
    node->left  = NULL;
    node->right = NULL;
    return node;
}


/* ============================================================
 *  MACHINE CODE ENCODERS
 *
 *  MIPS has 3 instruction formats. Each is 32 bits (4 bytes).
 *
 *  R-type: used for register operations like add, subtract
 *    [ opcode=0 (6) | rs (5) | rt (5) | rd (5) | shift (5) | funct (6) ]
 *
 *  I-type: used for immediate values and memory (load/store)
 *    [ opcode (6) | rs (5) | rt (5) | immediate (16) ]
 *
 *  J-type: used for jump instructions
 *    [ opcode (6) | address (26) ]
 *
 *  The numbers in parentheses are how many bits each field uses.
 * ============================================================ */

/* Extracts the register number from a name like "r5" → 5 */
int register_name_to_number(const char *reg_name) {
    if (!reg_name || reg_name[0] != 'r') return -1;
    int num = atoi(reg_name + 1); /* skip the 'r' and read the digits */
    if (num < 0 || num > 31) return -1;
    return num;
}

/* Encodes an R-type instruction into a 32-bit number */
uint32_t encode_r_type(int source_reg1, int source_reg2, int dest_reg, int shift_amount, int function_code) {
    return ((uint32_t)0 << 26)                          /* opcode is always 0 for R-type */
         | ((uint32_t)(source_reg1  & 0x1F) << 21)     /* rs: first source register */
         | ((uint32_t)(source_reg2  & 0x1F) << 16)     /* rt: second source register */
         | ((uint32_t)(dest_reg     & 0x1F) << 11)     /* rd: destination register */
         | ((uint32_t)(shift_amount & 0x1F) << 6)      /* sa: shift amount (0 for most) */
         | ((uint32_t)(function_code & 0x3F));          /* funct: specifies the operation */
}

/* Encodes an I-type instruction into a 32-bit number */
uint32_t encode_i_type(int opcode, int source_reg, int target_reg, int immediate_value) {
    return ((uint32_t)(opcode       & 0x3F) << 26)     /* opcode: identifies instruction type */
         | ((uint32_t)(source_reg   & 0x1F) << 21)     /* rs: base register */
         | ((uint32_t)(target_reg   & 0x1F) << 16)     /* rt: target register */
         | ((uint32_t)(immediate_value & 0xFFFF));      /* imm: 16-bit constant or offset */
}

/* Encodes a J-type instruction into a 32-bit number */
uint32_t encode_j_type(int opcode, int jump_address) {
    return ((uint32_t)(opcode        & 0x3F) << 26)    /* opcode */
         | ((uint32_t)(jump_address  & 0x3FFFFFF));     /* 26-bit jump target */
}


/* Prints one bit at a time from bit 31 down to bit 0 */
void print_bits(uint32_t instruction, int space_at_bit_positions[], int num_positions) {
    for (int bit = 31; bit >= 0; bit--) {
        putchar(((instruction >> bit) & 1) ? '1' : '0');
        /* Add a space after each field boundary */
        for (int j = 0; j < num_positions; j++) {
            if (bit == space_at_bit_positions[j]) {
                putchar(' ');
                break;
            }
        }
    }
    putchar('\n');
}

/* Print R-type: fields are [opcode|rs|rt|rd|sa|funct] */
void print_r_type_machine_code(uint32_t instruction) {
    printf("\tHex:    %08X\n", instruction);
    printf("\tBinary: ");
    int r_field_boundaries[] = {26, 21, 16, 11, 6};
    print_bits(instruction, r_field_boundaries, 5);
}

/* Print I-type: fields are [opcode|rs|rt|immediate] */
void print_i_type_machine_code(uint32_t instruction) {
    printf("\tHex:    %08X\n", instruction);
    printf("\tBinary: ");
    int i_field_boundaries[] = {26, 21, 16};
    print_bits(instruction, i_field_boundaries, 3);
}

/* Print J-type: fields are [opcode|address] */
void print_j_type_machine_code(uint32_t instruction) {
    printf("\tHex:    %08X\n", instruction);
    printf("\tBinary: ");
    int j_field_boundaries[] = {26};
    print_bits(instruction, j_field_boundaries, 1);
}


/* ================ LEXER ======================*/
int   current_line = 1;
FILE *source_file;

/* The recognized type keywords */
const char *type_keywords[MAX_KEYWORDS] = {"int"};

/*
 * Reads the next token from the source file.
 * Skips whitespace and newlines, then identifies what kind
 * of thing the next chunk of text is.
 */
Token get_next_token() {
    Token token;
    char  ch;
    int   char_index = 0;

    /* Initialize token to blank/unknown */
    token.text[0]      = '\0';
    token.type         = UNKNOWN;
    token.line_number  = current_line;

    /* --- Skip whitespace, but track line numbers --- */
    while ((ch = fgetc(source_file)) != EOF) {
        if (ch == '\n') { current_line++; continue; }
        if (!isspace((unsigned char)ch)) break; /* found a real character */
    }

    /* If we hit end of file, return a special EOF token */
    if (ch == EOF) {
        token.type = UNKNOWN;
        strcpy(token.text, "EOF");
        token.line_number = current_line;
        return token;
    }

    token.line_number = current_line;

    /* --- IDENTIFIER or KEYWORD: starts with a letter or underscore --- */
    if (isalpha((unsigned char)ch) || ch == '_') {
        token.text[char_index++] = ch;
        while ((ch = fgetc(source_file)) != EOF
               && (isalnum((unsigned char)ch) || ch == '_'))
            token.text[char_index++] = ch;
        token.text[char_index] = '\0';

        /* Put back the character that ended the word */
        if (ch != EOF) ungetc(ch, source_file);

        /* Check if it's a keyword like "int" */
        token.type = IDENTIFIER;
        for (int k = 0; k < MAX_KEYWORDS; k++)
            if (strcmp(token.text, type_keywords[k]) == 0)
                token.type = KEYWORD;

        return token;
    }

    /* --- NUMBER: starts with a digit --- */
    if (isdigit((unsigned char)ch)) {
        token.text[char_index++] = ch;
        while ((ch = fgetc(source_file)) != EOF && isdigit((unsigned char)ch))
            token.text[char_index++] = ch;
        token.text[char_index] = '\0';
        if (ch != EOF) ungetc(ch, source_file);
        token.type = NUMBER;
        return token;
    }

    /* --- OPERATOR: +, -, *, /, =, and their compound versions like +=, ++ --- */
    if (strchr("+-*/=", ch)) {
        char next_ch = fgetc(source_file);
        int is_compound = (next_ch != EOF) && (
            (ch == '+' && (next_ch == '+' || next_ch == '=')) ||
            (ch == '-' && (next_ch == '-' || next_ch == '=')) ||
            (ch == '*' &&  next_ch == '=') ||
            (ch == '/' &&  next_ch == '='));

        if (is_compound) {
            /* Two-character operator like +=, -=, ++, -- */
            token.text[0] = ch;
            token.text[1] = next_ch;
            token.text[2] = '\0';
        } else {
            /* Single-character operator like +, -, = */
            if (next_ch != EOF) ungetc(next_ch, source_file);
            token.text[0] = ch;
            token.text[1] = '\0';
        }
        token.type = OPERATOR;
        return token;
    }

    /* --- PUNCTUATION: ; , ( ) { } --- */
    if (strchr("(),;{}", ch)) {
        token.text[0] = ch;
        token.text[1] = '\0';
        token.type = PUNCTUATION;
        return token;
    }

    /* --- UNKNOWN: anything else --- */
    token.text[0] = ch;
    token.text[1] = '\0';
    token.type = UNKNOWN;
    return token;
}

/* Prints a single token (used for debugging) */
void print_token(Token token) {
    const char *type_label =
        token.type == IDENTIFIER  ? "IDENTIFIER"  :
        token.type == NUMBER      ? "NUMBER"       :
        token.type == OPERATOR    ? "OPERATOR"     :
        token.type == PUNCTUATION ? "PUNCTUATION"  :
        token.type == KEYWORD     ? "KEYWORD"      : "UNKNOWN";
    printf("%-12s : %s (line %d)\n", type_label, token.text, token.line_number);
}


/* ======================== PARSER ==================================== */

/* Forward declarations so functions can call each other */
ASTNode* parse_expression();
ASTNode* parse_term();
ASTNode* parse_factor();
ASTNode* parse_assignment_expression();
ASTNode* parse_assignment_statement();
ASTNode* parse_declaration();

/* The token we're currently looking at */
Token current_token;

/* Checks if we're at end of file */
int is_end_of_file() {
    return current_token.type == UNKNOWN
        && strcmp(current_token.text, "EOF") == 0;
}

/* Advance without counting (internal use only) */
void advance_silent() {
    current_token = get_next_token();
}

/*
 * Reads the next token and updates all the token counters.
 * This is how we move forward through the source file.
 */
void advance() {
    current_token = get_next_token();

    /* Count everything except EOF */
    if (!is_end_of_file()) {
        total_token_count++;
        if (all_tokens_count < MAX_TOKENS)
            all_tokens[all_tokens_count++] = current_token;
    }

    /* Update per-type counters */
    switch (current_token.type) {
        case IDENTIFIER:  count_identifiers++;  break;
        case NUMBER:      count_numbers++;       break;
        case OPERATOR:    count_operators++;     break;
        case PUNCTUATION: count_punctuations++;  break;
        case KEYWORD:     count_keywords++;      break;
        default:          count_unknown++;       break;
    }
}

/*
 * Expects the current token to match the given text.
 * If it does, advance. If not, record an error.
 */
void expect(const char *expected_text) {
    if (strcmp(current_token.text, expected_text) == 0) {
        advance();
    } else {
        add_error("Syntax error at line %d: expected '%s', got '%s'",
                  current_token.line_number, expected_text, current_token.text);
        if (!is_end_of_file())
            advance();
    }
}

/*
 * When we hit a bad statement, skip ahead until we find a semicolon
 * or the start of the next statement, so we can keep parsing.
 */
void skip_bad_statement() {
    int start_line = current_token.line_number;
    while (!is_end_of_file()) {
        if (strcmp(current_token.text, ";") == 0) {
            advance(); /* consume the semicolon */
            return;
        }
        /* Stop before the next statement starts */
        if (current_token.type == KEYWORD
         || current_token.type == IDENTIFIER
         || strcmp(current_token.text, "}") == 0
         || current_token.line_number > start_line)
            return; /* don't advance — let the caller see this token */

        advance();
    }
}

/* Prints the AST in a readable form (used for debugging) */
void print_ast(ASTNode *node) {
    if (!node) return;
    if (node->left)  { printf("("); print_ast(node->left); }
    printf(" %s ", node->token.text);
    if (node->right) { print_ast(node->right); printf(")"); }
}

/*
 * parse_factor — the smallest unit: a number, a variable, or (expression)
 *
 * Also handles unary minus: "-5" becomes "0 - 5"
 */
ASTNode* parse_factor() {
    ASTNode *node = NULL;

    /* Unary minus: treat "-x" as "0 - x" */
    if (current_token.type == OPERATOR
     && strcmp(current_token.text, "-") == 0) {
        Token minus_token = current_token;
        advance(); /* consume '-' */

        ASTNode *right_side = parse_factor(); /* what we're negating */

        /* Create a literal "0" node */
        Token zero_token;
        zero_token.type        = NUMBER;
        zero_token.line_number = minus_token.line_number;
        strcpy(zero_token.text, "0");

        ASTNode *zero_node   = create_tree_node(zero_token);
        ASTNode *minus_node  = create_tree_node(minus_token);
        minus_node->left     = zero_node;
        minus_node->right    = right_side;
        return minus_node;
    }

    /* A plain number like 42 */
    if (current_token.type == NUMBER) {
        node = create_tree_node(current_token);
        advance();
        return node;
    }

    /* A variable name like "a" */
    /* A variable name like "a" */
    if (current_token.type == IDENTIFIER) {
        node = create_tree_node(current_token);
        if (!variable_exists(current_token.text)) {
            add_error("Semantic error at line %d: variable '%s' is undeclared",
                    current_token.line_number, current_token.text);
        }
        advance();

        /* Handle postfix ++ and -- inside expressions */
        if (current_token.type == OPERATOR &&
        (strcmp(current_token.text, "++") == 0 ||
            strcmp(current_token.text, "--") == 0)) {
            Token op = current_token;
            advance();
            ASTNode *inc_node = create_tree_node(op);
            inc_node->left  = node;
            inc_node->right = NULL;
            return inc_node;
        }

        return node;
    }

    /* A parenthesized expression like (b + c) */
    if (strcmp(current_token.text, "(") == 0) {
        advance(); /* consume '(' */
        node = parse_expression();
        expect(")");
        return node;
    }

    /* Nothing matched — unexpected token */
    add_error("Error at line %d: unexpected token '%s'",
              current_token.line_number, current_token.text);
    advance();
    return NULL;
}

/*
 * parse_term — handles * and /
 * Example: "b * c" or "a / 2"
 */
ASTNode* parse_term() {
    ASTNode *node = parse_factor();

    while (current_token.type == OPERATOR
        && (strcmp(current_token.text, "*") == 0
         || strcmp(current_token.text, "/") == 0)) {
        Token    op         = current_token;
        advance();
        ASTNode *right_node = parse_factor();
        ASTNode *parent     = create_tree_node(op);
        parent->left        = node;
        parent->right       = right_node;
        node = parent;
    }
    return node;
}

/*
 * parse_expression — handles + and -
 * Example: "b + c" or "a - 1"
 */
ASTNode* parse_expression() {
    ASTNode *node = parse_term();

    while (current_token.type == OPERATOR
        && (strcmp(current_token.text, "+") == 0
         || strcmp(current_token.text, "-") == 0)) {
        Token    op         = current_token;
        advance();
        ASTNode *right_node = parse_term();
        ASTNode *parent     = create_tree_node(op);
        parent->left        = node;
        parent->right       = right_node;
        node = parent;
    }
    return node;
}

/*
 * parse_assignment_expression — handles = and compound operators (+=, -=, etc.)
 * This is right-associative: "a = b = 5" means "a = (b = 5)"
 */
ASTNode* parse_assignment_expression() {
    ASTNode *left = parse_expression();

    /* Only a variable name can be on the left side of an assignment */
    if (!left || left->token.type != IDENTIFIER) return left;

    if (current_token.type == OPERATOR
     && (strcmp(current_token.text, "=")  == 0
      || strcmp(current_token.text, "+=") == 0
      || strcmp(current_token.text, "-=") == 0
      || strcmp(current_token.text, "*=") == 0
      || strcmp(current_token.text, "/=") == 0)) {

        Token    assign_op  = current_token;
        advance(); /* consume the operator */

        /* Recurse to allow chaining: a = b = 5 */
        ASTNode *right_side = parse_assignment_expression();

        ASTNode *assign_node  = create_tree_node(assign_op);
        assign_node->left     = left;
        assign_node->right    = right_side;
        return assign_node;
    }

    return left; /* no assignment, just a plain expression */
}

/*
 * parse_assignment_statement — parses a full assignment line like:
 *   a = b + c;
 *   x++;
 *   y += 3;
 *
 * Returns the AST node for code generation, or NULL if nothing to emit.
 */
ASTNode* parse_assignment_statement() {
    if (current_token.type != IDENTIFIER) return NULL;

    Token    var_token = current_token;
    ASTNode *var_node  = create_tree_node(var_token);

    /* Make sure the variable was declared */
    if (!variable_exists(var_token.text)) {
        add_error("Error at line %d: variable '%s' is undeclared",
                  var_token.line_number, var_token.text);
        advance();
        skip_bad_statement();
        return NULL;
    }

    advance(); /* move past the variable name */

    /* Handle standalone "a;" — valid but has no effect */
    if (current_token.type == PUNCTUATION
     && strcmp(current_token.text, ";") == 0) {
        advance(); /* consume ';' */
        return NULL;
    }

    /* Handle postfix ++ and --: "a++" or "a--" */
    if (current_token.type == OPERATOR
     && (strcmp(current_token.text, "++") == 0
      || strcmp(current_token.text, "--") == 0)) {

        Token    inc_op   = current_token;
        advance(); /* consume ++ or -- */

        if (strcmp(current_token.text, ";") == 0)
            advance();
        else {
            add_error("Error at line %d: expected ';'", current_token.line_number);
            skip_bad_statement();
        }

        ASTNode *inc_node  = create_tree_node(inc_op);
        inc_node->left     = var_node;
        inc_node->right    = NULL;
        return inc_node;
    }

    /* Handle normal and compound assignment: =, +=, -=, *=, /= */
    if (current_token.type == OPERATOR
     && (strcmp(current_token.text, "=")  == 0
      || strcmp(current_token.text, "+=") == 0
      || strcmp(current_token.text, "-=") == 0
      || strcmp(current_token.text, "*=") == 0
      || strcmp(current_token.text, "/=") == 0)) {

        Token    assign_op   = current_token;
        advance(); /* consume the assignment operator */

        ASTNode *right_expr  = parse_assignment_expression();

        ASTNode *assign_node = create_tree_node(assign_op);
        assign_node->left    = var_node;
        assign_node->right   = right_expr;

        /* Consume the semicolon, or handle comma-separated assignments */
        if (strcmp(current_token.text, ";") == 0)
            advance();
        else if (strcmp(current_token.text, ",") == 0)
            return assign_node; /* caller will handle the comma */
        else {
            add_error("Error at line %d: expected ';'", current_token.line_number);
            skip_bad_statement();
        }

        return assign_node;
    }

    /* Unexpected token after variable name */
    add_error("Error at line %d: expected assignment operator, got '%s'",
              current_token.line_number, current_token.text);
    skip_bad_statement();
    return NULL;
}


/* ============================================================
 *  CONSTANT EXPRESSION EVALUATOR
 *  If an expression only uses numbers (no variables), we can
 *  calculate its value at compile time.
 *  Example: "3 + 4" → 7 (we know this without running the program)
 *  Example: "a + 1" → can't know (depends on what 'a' is at runtime)
 * ============================================================ */
int evaluate_constant(ASTNode *node, long *result) {
    if (!node) return 0;

    /* A plain number — we know its value */
    if (node->token.type == NUMBER) {
        *result = atol(node->token.text);
        return 1; /* yes, it's a constant */
    }

    /* A variable — we can't know its value at compile time */
    if (node->token.type == IDENTIFIER) return 0;

    /* An operation — only constant if both sides are constant */
    if (node->token.type == OPERATOR) {
        long left_val, right_val;
        if (!evaluate_constant(node->left,  &left_val))  return 0;
        if (!evaluate_constant(node->right, &right_val)) return 0;

        if (strcmp(node->token.text, "+") == 0) { *result = left_val + right_val; return 1; }
        if (strcmp(node->token.text, "-") == 0) { *result = left_val - right_val; return 1; }
        if (strcmp(node->token.text, "*") == 0) { *result = left_val * right_val; return 1; }
        if (strcmp(node->token.text, "/") == 0) {
            if (right_val == 0) {
                add_error("Runtime error: division by zero in constant expression");
                return 0;
            }
            *result = left_val / right_val;
            return 1;
        }
    }

    return 0;
}


/* ============================================================
 *  RUNTIME INITIALIZATION LIST
 *  Some declarations have initializers that need runtime code.
 *  Example: "int x = a + b;" — we can't know this at compile time,
 *  so we store the assignment AST and emit code for it later.
 * ============================================================ */
ASTNode *runtime_init_list[MAX_RUNTIME_INITS];
int      runtime_init_count = 0;

/* Current compiler pass: 1 = collect symbols, 2 = emit code */
int current_pass = 1;


/*
 * parse_declaration — handles variable declarations like:
 *   int a;
 *   int a, b, c;
 *   int x = 5;
 *   int y = a + 1;   (runtime init — gets emitted in .code section)
 */
ASTNode* parse_declaration() {
    if (current_token.type != KEYWORD) return NULL;

    int  decl_line = current_token.line_number;
    char type_name[MAX_WORD_LENGTH];
    strncpy(type_name, current_token.text, MAX_WORD_LENGTH - 1);
    type_name[MAX_WORD_LENGTH - 1] = '\0';

    advance(); /* consume "int" */

    /* Reject unsupported types — only int is allowed */
    if (strcmp(type_name, "int") != 0) {
        add_error("Error at line %d: unsupported type '%s'. Only 'int' is allowed.", decl_line, type_name);
        skip_bad_statement();
        return NULL;
    }

    /* Must be followed by at least one variable name */
    if (current_token.type != IDENTIFIER) {
        add_error("Error at line %d: expected variable name after '%s'", decl_line, type_name);
        skip_bad_statement();
        return NULL;
    }

    /* Loop to handle multiple declarations: int a, b, c; */
    while (!is_end_of_file()) {

        /* Must see a variable name */
        if (current_token.type != IDENTIFIER) {
            add_error("Error at line %d: expected variable name after '%s'", decl_line, type_name);
            skip_bad_statement();
            return NULL;
        }

        /* Register the variable name in the symbol table */
        char var_name[MAX_WORD_LENGTH];
        strncpy(var_name, current_token.text, MAX_WORD_LENGTH - 1);
        var_name[MAX_WORD_LENGTH - 1] = '\0';
        int var_idx = add_variable(var_name, IDENTIFIER);
        advance();

        /* Check for optional initializer: int x = 5 */
        if (current_token.type == OPERATOR
         && (strcmp(current_token.text, "=")  == 0
          || strcmp(current_token.text, "+=") == 0
          || strcmp(current_token.text, "-=") == 0
          || strcmp(current_token.text, "*=") == 0
          || strcmp(current_token.text, "/=") == 0)) {

            advance(); /* consume the = */
            ASTNode *init_expr = parse_expression();

            if (init_expr) {
                long const_value;
                int  is_compile_time_constant = evaluate_constant(init_expr, &const_value);

                if (is_compile_time_constant) {
                    /* We know the value right now — store it in the symbol table */
                    symbol_table[var_idx].initial_value  = const_value;
                    symbol_table[var_idx].is_initialized = 1;
                    /* Will be emitted in .data section */

                } else {
                    /* Value depends on other variables — generate runtime code */
                    symbol_table[var_idx].initial_value  = 0;
                    symbol_table[var_idx].is_initialized = 0;

                    if (current_pass == 1 && runtime_init_count < MAX_RUNTIME_INITS) {
                        /* Build an assignment AST: var_name = init_expr */
                        Token assign_token;
                        assign_token.type        = OPERATOR;
                        assign_token.line_number = current_token.line_number;
                        strcpy(assign_token.text, "=");

                        ASTNode *assign_node = create_tree_node(assign_token);

                        Token left_token;
                        left_token.type        = IDENTIFIER;
                        left_token.line_number = current_token.line_number;
                        left_token.text[0]     = '\0';
                        assign_node->left      = create_tree_node(left_token);
                        strcpy(assign_node->left->token.text, var_name);
                        assign_node->right     = init_expr;

                        runtime_init_list[runtime_init_count++] = assign_node;
                    }
                }
            } else {
                skip_bad_statement();
            }

        } else {
            /* No initializer — variable starts at 0 */
            symbol_table[var_idx].initial_value  = 0;
            symbol_table[var_idx].is_initialized = 0;
        }

        /* After each variable, expect either ',' (more variables) or ';' (end) */
        if (strcmp(current_token.text, ",") == 0) {
            advance(); /* comma → more variables coming */
            continue;
        } else if (strcmp(current_token.text, ";") == 0) {
            advance(); /* semicolon → declaration is done */
            break;
        } else if (is_end_of_file()) {
            add_error("Syntax error at line %d: unexpected end of file in declaration", decl_line);
            return NULL;
        } else {
            add_error("Syntax error at line %d: expected ',' or ';', got '%s'",
                      decl_line, current_token.text);
            skip_bad_statement();
            break;
        }
    }

    return NULL; /* declarations don't produce AST nodes directly */
}


/* ============================================================
 *  REGISTER ALLOCATOR
 *  Hands out registers r1, r2, r3, ... for temporary values.
 *  Wraps back to r1 if we run out (simple round-robin).
 * ============================================================ */
char temp_registers[32][8]; /* storage for register name strings */
int  next_register_number = 1;

/* Returns the next available register name, like "r3" */
char* allocate_register() {
    if (next_register_number >= 32)
        next_register_number = 1; /* wrap around */
    sprintf(temp_registers[next_register_number], "r%d", next_register_number);
    return temp_registers[next_register_number++];
}


/* dest_reg is the register where the result should be placed.*/
void emit_expression(ASTNode *node, const char *dest_reg) {
    if (!node || !dest_reg) return;

    /* ---- Case 1: It's a number (e.g. 42) ----
       Emit: daddiu dest_reg, r0, #42
       This loads the number into dest_reg.
       r0 is always 0 in MIPS, so this is: dest_reg = 0 + 42 */
    if (node->token.type == NUMBER) {
        printf("    daddiu %s, r0, #%s\n", dest_reg, node->token.text);

        int      target_reg   = register_name_to_number(dest_reg);
        long     num_value    = atol(node->token.text);
        uint32_t instruction  = encode_i_type(0x19, 0, target_reg, (int)num_value);
        /* opcode 0x19 = DADDIU (double-word add immediate unsigned) */

        print_i_type_machine_code(instruction);
        printf("\n");
        return;
    }

    /* ---- Case 2: It's a variable name (e.g. "b") ----
       If already in a register, reuse it.
       Otherwise, load it from memory: ld dest_reg, varname(r0) */
    if (node->token.type == IDENTIFIER) {
        /* Find the variable in the symbol table */
        int var_idx = -1;
        for (int i = 0; i < variable_count; i++)
            if (strcmp(symbol_table[i].name, node->token.text) == 0)
                var_idx = i;

        if (var_idx != -1) {
            int existing_register = variable_register_map[var_idx];

            if (existing_register != -1) {
                /* Variable is already in a register — reuse it */
                sprintf((char*)dest_reg, "r%d", existing_register);
                return;
            } else {
                /* Not in a register — load from memory */
                int      target_reg  = register_name_to_number(dest_reg);
                uint32_t instruction = encode_i_type(0x37, 0, target_reg, 0);
                /* opcode 0x37 = LD (load doubleword) */

                printf("    ld %s, %s(r0)\n", dest_reg, symbol_table[var_idx].name);
                print_i_type_machine_code(instruction);

                variable_register_map[var_idx] = target_reg; /* remember it's loaded */
                return;
            }
        }
        return;
    }

    /* CASE 3 */
    if (strcmp(node->token.text, "++") == 0 ||
        strcmp(node->token.text, "--") == 0) {

        int delta = (strcmp(node->token.text, "++") == 0) ? 1 : -1;

        int var_idx = -1;
        for (int i = 0; i < variable_count; i++)
            if (strcmp(symbol_table[i].name, node->left->token.text) == 0)
                var_idx = i;

        int reg = register_name_to_number(dest_reg);

        /* Step 1: load */
        printf("    ld %s, %s(r0)\n", dest_reg, symbol_table[var_idx].name);
        uint32_t instr = encode_i_type(0x37, 0, reg, 0);
        print_i_type_machine_code(instr);

        /* Step 2: add 1 or -1 */
        printf("    daddiu %s, %s, #%d\n", dest_reg, dest_reg, delta);
        instr = encode_i_type(0x19, reg, reg, delta);
        print_i_type_machine_code(instr);
        printf("\n");

        /* Step 3: NO store — emit_assignment() handles it */
        variable_register_map[var_idx] = reg;
        return;
    }

    /* ---- Case 4: It's an operator (e.g. +, -, *, /) ----
       Evaluate left and right sides into temp registers,
       then combine them into dest_reg. */
    if (node->token.type == OPERATOR) {
        char *left_reg  = allocate_register();
        char *right_reg = allocate_register();

        /* Recursively evaluate both sides */
        emit_expression(node->left,  left_reg);
        emit_expression(node->right, right_reg);

        /* Get register numbers for encoding */
        int dest  = register_name_to_number(dest_reg);
        int left  = register_name_to_number(left_reg);
        int right = register_name_to_number(right_reg);
        uint32_t instruction = 0;

        if (strcmp(node->token.text, "+") == 0) {
            printf("    daddu %s, %s, %s\n", dest_reg, left_reg, right_reg);
            instruction = encode_r_type(left, right, dest, 0, 0x2D);
            /* DADDU funct=0x2D: dest = left + right (unsigned 64-bit) */

        } else if (strcmp(node->token.text, "-") == 0) {
            printf("    dsubu %s, %s, %s\n", dest_reg, left_reg, right_reg);
            instruction = encode_r_type(left, right, dest, 0, 0x2F);
            /* DSUBU funct=0x2F: dest = left - right */

        } else if (strcmp(node->token.text, "*") == 0) {
            printf("    dmul %s, %s, %s\n", dest_reg, left_reg, right_reg);
            instruction = encode_r_type(left, right, dest, 2, 0x1C);
            /* DMUL funct=0x1C, sa=2: dest = left * right */

        } else if (strcmp(node->token.text, "/") == 0) {
            printf("    ddiv %s, %s, %s\n", dest_reg, left_reg, right_reg);
            instruction = encode_r_type(left, right, dest, 2, 0x1E);
            /* DDIV funct=0x1E, sa=2: dest = left / right */

        } else {
            printf("    /* unknown operator: %s */\n", node->token.text);
        }

        print_r_type_machine_code(instruction);
        printf("\n");
        return;
    }
}


/* ============================================================
 *  CODE GENERATOR — ASSIGNMENT STATEMENTS
 *  Handles all kinds of assignment:
 *    a = expr       → simple assignment
 *    a += expr      → compound assignment (load, operate, store)
 *    a++  / a--     → increment / decrement
 * ============================================================ */
void emit_assignment(ASTNode *assign_node) {
    if (!assign_node) return;

    /* Find the variable being assigned to */
    int var_idx = -1;
    for (int i = 0; i < variable_count; i++)
        if (strcmp(symbol_table[i].name, assign_node->left->token.text) == 0)
            var_idx = i;

    if (var_idx == -1) {
        printf("    /* ERROR: unknown variable '%s' */\n",
               assign_node->left->token.text);
        return;
    }

    char *result_reg = allocate_register(); /* register for the computed value */

    /* ---- Case 1: Increment / Decrement (++ or --) ----
       Steps: load variable → add 1 or -1 → store back */
    if (strcmp(assign_node->token.text, "++") == 0
     || strcmp(assign_node->token.text, "--") == 0) {

        int delta = (strcmp(assign_node->token.text, "++") == 0) ? 1 : -1;
        int reg   = register_name_to_number(result_reg);

        /* Load current value */
        printf("    ld %s, %s(r0)\n", result_reg, symbol_table[var_idx].name);
        uint32_t instr = encode_i_type(0x37, 0, reg, 0);
        print_i_type_machine_code(instr);

        /* Add +1 or -1 */
        printf("    daddiu %s, %s, #%d\n", result_reg, result_reg, delta);
        instr = encode_i_type(0x19, reg, reg, delta);
        print_i_type_machine_code(instr);
        printf("\n");

        /* Store updated value */
        printf("    sd %s, %s(r0)\n", result_reg, symbol_table[var_idx].name);
        instr = encode_i_type(0x3F, 0, reg, 0);
        /* opcode 0x3F = SD (store doubleword) */
        print_i_type_machine_code(instr);

        variable_register_map[var_idx] = reg;
        return;
    }

    /* ---- Case 2: Compound Assignment (+=, -=, *=, /=) ----
       Steps: load old value → compute RHS → apply operation → store back */
    if (strcmp(assign_node->token.text, "+=") == 0
     || strcmp(assign_node->token.text, "-=") == 0
     || strcmp(assign_node->token.text, "*=") == 0
     || strcmp(assign_node->token.text, "/=") == 0) {

        char *old_value_reg = allocate_register();
        int   rv            = register_name_to_number(old_value_reg);

        /* Load current value of the variable */
        printf("    ld %s, %s(r0)\n", old_value_reg, symbol_table[var_idx].name);
        uint32_t instr = encode_i_type(0x37, 0, rv, 0);
        print_i_type_machine_code(instr);

        /* Evaluate the right-hand side expression */
        emit_expression(assign_node->right, result_reg);
        int rr = register_name_to_number(result_reg);

        /* Apply the operation: old_value_reg = old_value_reg OP result_reg */
        instr = 0;
        if (strcmp(assign_node->token.text, "+=") == 0) {
            printf("    daddu %s, %s, %s\n", old_value_reg, old_value_reg, result_reg);
            instr = encode_r_type(rv, rr, rv, 0, 0x2D);
        } else if (strcmp(assign_node->token.text, "-=") == 0) {
            printf("    dsubu %s, %s, %s\n", old_value_reg, old_value_reg, result_reg);
            instr = encode_r_type(rv, rr, rv, 0, 0x2F);
        } else if (strcmp(assign_node->token.text, "*=") == 0) {
            printf("    dmul %s, %s, %s\n", old_value_reg, old_value_reg, result_reg);
            instr = encode_r_type(rv, rr, rv, 2, 0x1C);
        } else if (strcmp(assign_node->token.text, "/=") == 0) {
            printf("    ddiv %s, %s, %s\n", old_value_reg, old_value_reg, result_reg);
            instr = encode_r_type(rv, rr, rv, 2, 0x1E);
        }
        print_r_type_machine_code(instr);
        printf("\n");

        /* Store the result back to memory */
        printf("    sd %s, %s(r0)\n", old_value_reg, symbol_table[var_idx].name);
        instr = encode_i_type(0x3F, 0, rv, 0);
        print_i_type_machine_code(instr);

        variable_register_map[var_idx] = rv;
        return;
    }

    /* ---- Case 3: Simple Assignment (=) ----
       Evaluate the right side, then store result into the variable */
    emit_expression(assign_node->right, result_reg);

    printf("    sd %s, %s(r0)\n", result_reg, symbol_table[var_idx].name);
    /* opcode 0x3F = SD: store the register value into memory at var address */
    int      target_reg  = register_name_to_number(result_reg);
    uint32_t instr       = encode_i_type(0x3F, 0, target_reg, 0);
    print_i_type_machine_code(instr);

    variable_register_map[var_idx] = target_reg;
}


/* ============================================================
 *  MAIN — Ties everything together
 *
 *  The program runs in TWO PASSES over the source file:
 *
 *  PASS 1 — "Read and check":
 *    - Tokenize the file
 *    - Build the symbol table (find all declared variables)
 *    - Collect any errors (undeclared variables, syntax mistakes)
 *    - If errors found → print them and stop
 *
 *  PASS 2 — "Generate output":
 *    - Rewind the file to the beginning
 *    - Emit the .data section (variable declarations)
 *    - Emit the .code section (assembly + machine code for each statement)
 * ============================================================ */
int main() {
    /* --- Open the source file --- */
    source_file = fopen("index.txt", "r");
    if (!source_file) {
        printf("Error: could not open index.txt\n");
        return 1;
    }

    /* ========================================================
     *  PASS 1: Collect symbols and check for errors
     * ======================================================== */
    fseek(source_file, 0, SEEK_SET);
    current_line  = 1;
    current_pass  = 1;

    advance(); /* read the very first token to get started */

    while (!is_end_of_file()) {

        /* Skip lone semicolons (empty statements like ";;") */
        if (current_token.type == PUNCTUATION
         && strcmp(current_token.text, ";") == 0) {
            count_empty_stmts++;
            advance();
            continue;
        }

        if (current_token.type == KEYWORD) {
            /* Variable declaration: int a, b, c; */
            parse_declaration();

        } else if (current_token.type == IDENTIFIER) {
            /* Assignment statement: a = b + c; */
            parse_assignment_statement();

        } else if (current_token.type == NUMBER
                || strcmp(current_token.text, "(") == 0) {
            /* Standalone expression: 3 + 4; (parse but don't emit) */
            parse_expression();
            expect(";");

        } else {
            advance(); /* skip unrecognized tokens */
        }
    }

    /* If any errors were found, print them and stop */
    if (error_count > 0) {
        for (int i = 0; i < error_count; i++)
            printf("%s\n", error_list[i]);
        printf("\nErrors detected. Stopping.\n");
        fclose(source_file);
        return 1;
    }

    /* ========================================================
     *  PASS 2: Generate the assembly and machine code output
     * ======================================================== */
    fseek(source_file, 0, SEEK_SET); /* rewind to beginning */
    current_line = 1;
    current_pass = 2;

    /* Reset all token counters for the second pass */
    all_tokens_count   = 0;
    total_token_count  = 0;
    count_identifiers  = 0;
    count_numbers      = 0;
    count_operators    = 0;
    count_punctuations = 0;
    count_keywords     = 0;
    count_unknown      = 0;
    count_empty_stmts  = 0;

    advance(); /* re-prime the token stream */

    /* Reset register allocator and register map */
    next_register_number = 1;
    for (int i = 0; i < variable_count; i++)
        variable_register_map[i] = -1;

    /* Calculate where each variable lives in memory */
    compute_memory_offsets();

    /* --- Emit .data section ---
       Lists all variables with their initial values */
    printf("\n.data\n");
    for (int i = 0; i < variable_count; i++) {
        if (symbol_table[i].is_initialized)
            printf("    %s: .word64 %ld\n", symbol_table[i].name, symbol_table[i].initial_value);
        else
            printf("    %s: .word64 0\n", symbol_table[i].name);
    }

    /* --- Emit .code section ---
       First: emit any runtime initialization code (from declarations like int x = a + b)
       Then:  process each assignment statement in the source file */
    printf("\n.code\n");

    /* Emit runtime initializations first (order preserved from pass 1) */
    for (int i = 0; i < runtime_init_count; i++)
        emit_assignment(runtime_init_list[i]);

    /* Now process the rest of the file for regular assignment statements */
    while (!is_end_of_file()) {

        /* Skip lone semicolons */
        if (current_token.type == PUNCTUATION
         && strcmp(current_token.text, ";") == 0) {
            count_empty_stmts++;
            advance();
            continue;
        }

        if (current_token.type == KEYWORD) {
            /* Declaration — already handled, just consume the tokens */
            parse_declaration();

        } else if (current_token.type == IDENTIFIER) {
            /* One or more assignments on the same line: a = 1, b = 2; */
            int current_stmt_line = current_token.line_number;

            while (current_token.type == IDENTIFIER
                && current_token.line_number == current_stmt_line) {

                ASTNode *one_assignment = parse_assignment_statement();
                if (one_assignment)
                    emit_assignment(one_assignment);

                /* If there's a comma, there's another assignment on this line */
                if (current_token.type == PUNCTUATION
                 && strcmp(current_token.text, ",") == 0
                 && current_token.line_number == current_stmt_line) {
                    advance(); /* consume ',' and continue */
                    continue;
                }
                break;
            }

        } else if (current_token.type == NUMBER
                || strcmp(current_token.text, "(") == 0) {
            /* Standalone expression — evaluate into a temp register */
            ASTNode *expr = parse_expression();
            if (expr) {
                char *temp_reg = allocate_register();
                emit_expression(expr, temp_reg);
            }
            expect(";");

        } else {
            advance();
        }
    }

    /* End of program */
    printf("\n    SYSCALL 0\n");
    printf("\nToken Count: %d\n", total_token_count);

    fclose(source_file);
    return 0;
}