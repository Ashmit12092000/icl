/**
 * Main JavaScript file for Loan Management System
 * Handles NaN prevention, form validation, and UI interactions
 */

// Global application object
const LoanApp = {
    // Configuration
    config: {
        dateFormat: 'DD-MM-YYYY',
        currencySymbol: '₹',
        decimalPlaces: 2
    },
    
    // Utility functions for handling numbers safely
    utils: {
        /**
         * Safely convert value to number, preventing NaN
         * @param {*} value - Value to convert
         * @param {number} defaultValue - Default value if conversion fails
         * @returns {number} - Safe number value
         */
        safeNumber(value, defaultValue = 0) {
            if (value === null || value === undefined || value === '') {
                return defaultValue;
            }
            
            const num = parseFloat(value);
            return isNaN(num) ? defaultValue : num;
        },
        
        /**
         * Format currency value safely
         * @param {*} value - Value to format
         * @returns {string} - Formatted currency string
         */
        formatCurrency(value) {
            const num = this.safeNumber(value);
            return `${LoanApp.config.currencySymbol}${num.toFixed(LoanApp.config.decimalPlaces).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`;
        },
        
        /**
         * Format percentage value safely
         * @param {*} value - Value to format
         * @returns {string} - Formatted percentage string
         */
        formatPercentage(value) {
            const num = this.safeNumber(value);
            return `${num.toFixed(2)}%`;
        },
        
        /**
         * Validate numeric input
         * @param {HTMLElement} input - Input element
         * @returns {boolean} - True if valid
         */
        validateNumericInput(input) {
            const value = input.value.trim();
            if (value === '') return true; // Allow empty values
            
            const num = parseFloat(value);
            if (isNaN(num)) {
                this.showInputError(input, 'Please enter a valid number');
                return false;
            }
            
            if (num < 0) {
                this.showInputError(input, 'Please enter a positive number');
                return false;
            }
            
            this.clearInputError(input);
            return true;
        },
        
        /**
         * Show input validation error
         * @param {HTMLElement} input - Input element
         * @param {string} message - Error message
         */
        showInputError(input, message) {
            input.classList.add('is-invalid');
            
            // Remove existing error message
            const existingError = input.parentNode.querySelector('.invalid-feedback');
            if (existingError) {
                existingError.remove();
            }
            
            // Add new error message
            const errorDiv = document.createElement('div');
            errorDiv.className = 'invalid-feedback';
            errorDiv.textContent = message;
            input.parentNode.appendChild(errorDiv);
        },
        
        /**
         * Clear input validation error
         * @param {HTMLElement} input - Input element
         */
        clearInputError(input) {
            input.classList.remove('is-invalid');
            const errorDiv = input.parentNode.querySelector('.invalid-feedback');
            if (errorDiv) {
                errorDiv.remove();
            }
        },
        
        /**
         * Calculate days between two dates
         * @param {string} fromDate - Start date (YYYY-MM-DD)
         * @param {string} toDate - End date (YYYY-MM-DD)
         * @returns {number} - Number of days
         */
        calculateDays(fromDate, toDate) {
            if (!fromDate || !toDate) return 0;
            
            const from = new Date(fromDate);
            const to = new Date(toDate);
            
            if (isNaN(from.getTime()) || isNaN(to.getTime())) return 0;
            
            const diffTime = Math.abs(to - from);
            return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        }
    },
    
    // Form handling functions
    forms: {
        /**
         * Initialize form validation
         */
        init() {
            // Add validation to all numeric inputs
            document.querySelectorAll('input[type="number"]').forEach(input => {
                input.addEventListener('blur', (e) => {
                    LoanApp.utils.validateNumericInput(e.target);
                });
                
                input.addEventListener('input', (e) => {
                    // Clear error on input
                    LoanApp.utils.clearInputError(e.target);
                    
                    // Update related calculations if needed
                    this.updateCalculations(e.target);
                });
            });
            
            // Add validation to date inputs
            document.querySelectorAll('input[type="date"]').forEach(input => {
                input.addEventListener('change', (e) => {
                    this.validateDateInput(e.target);
                });
            });
            
            // Prevent form double submission
            document.querySelectorAll('form').forEach(form => {
                form.addEventListener('submit', (e) => {
                    this.handleFormSubmission(e);
                });
            });
        },
        
        /**
         * Validate date input
         * @param {HTMLElement} input - Date input element
         */
        validateDateInput(input) {
            const value = input.value;
            if (!value) return true;
            
            const date = new Date(value);
            if (isNaN(date.getTime())) {
                LoanApp.utils.showInputError(input, 'Please enter a valid date');
                return false;
            }
            
            // Check if date is not too far in the future
            const today = new Date();
            const oneYearFromNow = new Date(today.getFullYear() + 1, today.getMonth(), today.getDate());
            
            if (date > oneYearFromNow) {
                if (!confirm('The selected date is more than a year in the future. Are you sure this is correct?')) {
                    input.focus();
                    return false;
                }
            }
            
            LoanApp.utils.clearInputError(input);
            return true;
        },
        
        /**
         * Update calculations based on input changes
         * @param {HTMLElement} input - Changed input element
         */
        updateCalculations(input) {
            const form = input.closest('form');
            if (!form) return;
            
            // Handle transaction form calculations
            if (form.id === 'transactionForm') {
                this.updateTransactionCalculations(form);
            }
            
            // Handle period calculations
            if (input.name === 'period_from' || input.name === 'period_to') {
                this.updatePeriodCalculations(form);
            }
        },
        
        /**
         * Update transaction balance calculations
         * @param {HTMLElement} form - Transaction form
         */
        updateTransactionCalculations(form) {
            const amountPaidInput = form.querySelector('input[name="amount_paid"]');
            const amountRepaidInput = form.querySelector('input[name="amount_repaid"]');
            const balanceDisplay = form.querySelector('#current_balance_display');
            
            if (!amountPaidInput || !amountRepaidInput || !balanceDisplay) return;
            
            // Get current balance from the display (extract number from currency format)
            const currentBalanceText = balanceDisplay.value || '₹0.00';
            const currentBalance = LoanApp.utils.safeNumber(currentBalanceText.replace(/[₹,]/g, ''));
            
            const amountPaid = LoanApp.utils.safeNumber(amountPaidInput.value);
            const amountRepaid = LoanApp.utils.safeNumber(amountRepaidInput.value);
            
            const newBalance = currentBalance + amountPaid - amountRepaid;
            balanceDisplay.value = LoanApp.utils.formatCurrency(newBalance);
            
            // Add visual indicator for balance change
            if (newBalance > currentBalance) {
                balanceDisplay.classList.add('text-success');
                balanceDisplay.classList.remove('text-danger', 'text-muted');
            } else if (newBalance < currentBalance) {
                balanceDisplay.classList.add('text-danger');
                balanceDisplay.classList.remove('text-success', 'text-muted');
            } else {
                balanceDisplay.classList.add('text-muted');
                balanceDisplay.classList.remove('text-success', 'text-danger');
            }
        },
        
        /**
         * Update period calculations (days)
         * @param {HTMLElement} form - Form containing period inputs
         */
        updatePeriodCalculations(form) {
            const fromInput = form.querySelector('input[name="period_from"]');
            const toInput = form.querySelector('input[name="period_to"]');
            
            if (!fromInput || !toInput) return;
            
            const fromDate = fromInput.value;
            const toDate = toInput.value;
            
            if (fromDate && toDate) {
                const days = LoanApp.utils.calculateDays(fromDate, toDate);
                
                // Show calculated days somewhere (you might want to add a display element)
                console.log(`Period: ${days} days`);
                
                // Validate date range
                if (new Date(fromDate) > new Date(toDate)) {
                    LoanApp.utils.showInputError(toInput, 'End date must be after start date');
                } else {
                    LoanApp.utils.clearInputError(toInput);
                    LoanApp.utils.clearInputError(fromInput);
                }
            }
        },
        
        /**
         * Handle form submission to prevent double submission
         * @param {Event} e - Submit event
         */
        handleFormSubmission(e) {
            const form = e.target;
            const submitButton = form.querySelector('button[type="submit"]');
            
            // Check if form is already being submitted
            if (form.classList.contains('form-loading')) {
                e.preventDefault();
                return false;
            }
            
            // Validate all numeric inputs
            const numericInputs = form.querySelectorAll('input[type="number"]');
            let hasErrors = false;
            
            numericInputs.forEach(input => {
                if (!LoanApp.utils.validateNumericInput(input)) {
                    hasErrors = true;
                }
            });
            
            if (hasErrors) {
                e.preventDefault();
                return false;
            }
            
            // Mark form as loading
            form.classList.add('form-loading');
            
            if (submitButton) {
                submitButton.disabled = true;
                const originalText = submitButton.innerHTML;
                submitButton.innerHTML = '<span class="loading-spinner"></span> Processing...';
                
                // Reset button after 5 seconds (fallback)
                setTimeout(() => {
                    form.classList.remove('form-loading');
                    submitButton.disabled = false;
                    submitButton.innerHTML = originalText;
                }, 5000);
            }
            
            return true;
        }
    },
    
    // DataTables enhancement
    tables: {
        /**
         * Initialize enhanced DataTables
         */
        init() {
            // Only initialize non-customer tables to avoid conflicts
            $('.table:not(#customersTable):not(#customerSummaryTable):not(#dashboardCustomersTable)').each(function() {
                if ($(this).data('no-datatable')) return;
                
                const $table = $(this);
                const tableId = $table.attr('id') || 'unnamed-table';
                
                // Complete cleanup before initialization
                app.destroyDataTable('#' + tableId);
                
                const options = {
                    destroy: true, // Allow reinitialization
                    responsive: true,
                    pageLength: 10,
                    order: [[0, 'desc']], // Default sort by first column descending
                    language: {
                        search: "Search:",
                        lengthMenu: "Show _MENU_ entries",
                        info: "Showing _START_ to _END_ of _TOTAL_ entries",
                        infoEmpty: "No entries available",
                        infoFiltered: "(filtered from _MAX_ total entries)",
                        zeroRecords: "No matching records found",
                        emptyTable: "No data available in table"
                    },
                    columnDefs: [
                        {
                            targets: 'no-sort',
                            orderable: false
                        },
                        {
                            targets: 'currency',
                            type: 'num-fmt',
                            render: function(data, type, row) {
                                if (type === 'display' || type === 'type') {
                                    const num = LoanApp.utils.safeNumber(data);
                                    return LoanApp.utils.formatCurrency(num);
                                }
                                return LoanApp.utils.safeNumber(data);
                            }
                        },
                        {
                            targets: 'percentage',
                            type: 'num-fmt',
                            render: function(data, type, row) {
                                if (type === 'display' || type === 'type') {
                                    const num = LoanApp.utils.safeNumber(data);
                                    return LoanApp.utils.formatPercentage(num);
                                }
                                return LoanApp.utils.safeNumber(data);
                            }
                        }
                    ]
                };
                
                // Initialize DataTable
                try {
                    $table.DataTable(options);
                    console.log('DataTable initialized for:', tableId);
                } catch (error) {
                    console.warn('DataTable initialization failed for', tableId, ':', error);
                }
            });
            
            // Initialize customer summary table for reports page
            this.initCustomerSummaryTable();
        },
        
        // Initialize customer summary table on reports page
        initCustomerSummaryTable() {
            const summaryTable = document.getElementById('customerSummaryTable');
            if (!summaryTable) return;
            
            app.destroyDataTable('#customerSummaryTable');
            
            try {
                $('#customerSummaryTable').DataTable({
                    destroy: true,
                    responsive: true,
                    pageLength: 15,
                    order: [[0, 'asc']],
                    columnDefs: [
                        { targets: [7], orderable: false } // Actions column
                    ],
                    language: {
                        search: "Search customers:",
                        lengthMenu: "Show _MENU_ customers",
                        info: "Showing _START_ to _END_ of _TOTAL_ customers"
                    }
                });
                console.log('Customer summary DataTable initialized');
            } catch (error) {
                console.error('Failed to initialize customer summary DataTable:', error);
            }
        }
    },
    
    // Initialize the application
    init() {
        // Wait for DOM to be ready
        $(document).ready(() => {
            console.log('Loan Management System initialized');
            
            // Initialize components
            this.forms.init();
            this.tables.init();
            
            // Initialize customer table if present
            this.initCustomerTable();
            
            // Handle customer deletion success and modal setup
            this.handleCustomerPageInit();
            
            // Set up global error handling
            window.addEventListener('error', (e) => {
                console.error('JavaScript Error:', e.error);
                // You might want to show a user-friendly error message
            });
            
            // Handle unhandled promise rejections
            window.addEventListener('unhandledrejection', (e) => {
                console.error('Unhandled Promise Rejection:', e.reason);
                e.preventDefault();
            });
            
            // Auto-hide alerts after 5 seconds
            $('.alert').each(function() {
                const $alert = $(this);
                if (!$alert.hasClass('alert-permanent')) {
                    setTimeout(() => {
                        $alert.fadeOut();
                    }, 5000);
                }
            });
            
            // Initialize tooltips if Bootstrap is available
            if (typeof bootstrap !== 'undefined') {
                const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
                tooltipTriggerList.map(function (tooltipTriggerEl) {
                    return new bootstrap.Tooltip(tooltipTriggerEl);
                });
            }
            
            // Add smooth animations to page elements
            this.addPageAnimations();
        });
    },
    
    // Add smooth animations to page elements
    addPageAnimations() {
        // Animate cards on page load
        $('.card').each(function(index) {
            $(this).css({
                'opacity': '0',
                'transform': 'translateY(20px)'
            }).delay(index * 100).animate({
                'opacity': '1'
            }, 500).css({
                'transform': 'translateY(0)'
            });
        });
        
        // Animate tables on page load
        $('.table').each(function(index) {
            $(this).css({
                'opacity': '0',
                'transform': 'translateY(20px)'
            }).delay(200 + index * 100).animate({
                'opacity': '1'
            }, 500).css({
                'transform': 'translateY(0)'
            });
        });
        
        // Add hover animations to buttons
        $('.btn').hover(
            function() {
                $(this).addClass('shadow-sm').css('transform', 'translateY(-1px)');
            },
            function() {
                $(this).removeClass('shadow-sm').css('transform', 'translateY(0)');
            }
        );
    },
    
    // Simplified customer table initialization 
    initCustomerTable() {
        const customerTable = document.getElementById('customersTable');
        if (!customerTable) return;
        
        // Check if table has valid structure
        const tbody = customerTable.querySelector('tbody');
        if (!tbody) return;
        
        const hasEmptyState = tbody.innerHTML.includes('No customers found');
        
        // Complete cleanup first
        this.destroyDataTable('#customersTable');
        
        // Don't initialize DataTable if we have empty state
        if (hasEmptyState) {
            console.log('Skipping DataTable initialization - empty state detected');
            return;
        }
        
        // Wait for DOM to settle after deletion
        setTimeout(() => {
            try {
                // Basic configuration to avoid cell index issues
                $('#customersTable').DataTable({
                    destroy: true,
                    pageLength: 10,
                    responsive: true,
                    language: {
                        search: "Search customers:",
                        emptyTable: "No customers available"
                    },
                    columnDefs: [
                        { targets: [10], orderable: false } // Actions column only
                    ]
                });
                
                console.log('Customer DataTable initialized successfully');
            } catch (error) {
                console.error('Failed to initialize customer DataTable:', error);
                // If DataTable fails, at least ensure basic functionality
                $('#customersTable').removeClass('dataTable');
            }
        }, 150);
    },
    
    // Enhanced DataTable cleanup utility
    destroyDataTable(selector) {
        try {
            if ($.fn.DataTable.isDataTable(selector)) {
                const table = $(selector).DataTable();
                table.clear().draw();
                table.destroy(true); // Remove from DOM completely
                console.log('DataTable destroyed:', selector);
            }
            
            // More thorough cleanup
            const $table = $(selector);
            
            // Remove wrapper elements
            $table.closest('.dataTables_wrapper').remove();
            $(selector + '_wrapper').remove();
            
            // Reset table to original state (preserve essential attributes)
            $table.removeClass('dataTable no-footer dtr-inline collapsed')
                  .removeAttr('role aria-describedby width style')
                  .removeData();
            
            // Clean up any cell indexes that might be causing issues
            $table.find('td, th').each(function() {
                delete this._DT_CellIndex;
                $(this).removeAttr('tabindex class style');
            });
            
            // Remove any DataTables event listeners
            $table.off('.dt');
            
        } catch (error) {
            console.warn('Error during DataTable cleanup:', error);
            // Force cleanup even if there are errors
            try {
                $(selector).replaceWith($(selector).clone());
            } catch (e) {
                console.warn('Force cleanup failed:', e);
            }
        }
    },
    
    // Handle customer page initialization
    handleCustomerPageInit() {
        if (window.location.pathname.includes('customer_master')) {
            // Handle add customer modal
            const addCustomerBtn = document.getElementById('addCustomerBtn');
            const addCustomerBtnEmpty = document.getElementById('addCustomerBtnEmpty');
            const addCustomerModal = document.getElementById('addCustomerModal');
            
            if (addCustomerModal) {
                const modal = new bootstrap.Modal(addCustomerModal);
                
                if (addCustomerBtn) {
                    addCustomerBtn.addEventListener('click', () => {
                        modal.show();
                    });
                }
                
                if (addCustomerBtnEmpty) {
                    addCustomerBtnEmpty.addEventListener('click', () => {
                        modal.show();
                    });
                }
            }
            
            // Handle customer deletion success - reinitialize table
            if (window.location.search.includes('deleted=1')) {
                // Remove the parameter from URL
                const url = new URL(window.location);
                url.searchParams.delete('deleted');
                window.history.replaceState({}, '', url);
                
                // Reinitialize table after deletion
                setTimeout(() => {
                    this.initCustomerTable();
                }, 200);
            }
        }
    }
};

// Initialize the application
LoanApp.init();

// Export for global access
window.LoanApp = LoanApp;
